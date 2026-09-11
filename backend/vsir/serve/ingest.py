"""``POST /documents`` — hand a PDF to the pipeline over HTTP (§6.1, §15 Factor XII).

**This route does not implement ingestion. It starts `vsir ingest`.**

That is the whole design, and it is a direct response to register item **E1**: `impl` had an upload
page *and* a CLI, the exports were written from the CLI path only, and so *"a UI ingest produced
nothing for the graph team"*. Two code paths for one operation meant one of them silently did less
than the whole job. §15 Factor XII settles it the other way round — *"a corrective action that
cannot be expressed as a `vsir` subcommand is not a supported operation"* — so the transport spools
the bytes, validates what it can refuse cheaply, and execs the same subcommand an operator would
run, from the same image and the same release. There is no second pipeline to drift.

What the caller gets back is ``202`` and a ``run_id``, immediately. Progress is
``GET /runs/{run_id}``, which already exists and reads the control plane rather than this process
(§6.9, D9) — so a poll works from any replica, not only the one that took the upload.

**Two properties an operator has to know they are giving up.**

*It makes the web process briefly stateful.* PyMuPDF needs a file, so an uploaded PDF is spooled to
disk for the life of one run, and §15 Factor VI's *"nothing on the instance to read"* stops being
literally true for that window. The spool is removed when the child exits, however it exits.

**What used to be disclosed here — that a run started by upload is not resumable across an instance
restart — is closed by U029.** It was true, and it was a real asymmetry: the spool went with the
instance while a CLI ingest stayed resumable only because the operator's own copy was still on
their filesystem. The document store fixes it at the source rather than by keeping the spool
around: step 02 of the pipeline deposits the document under ``<doc_id>@<revision>.pdf`` on a
mounted volume, and because this route *runs that pipeline*, an upload deposits through exactly the
same line a CLI ingest does. ``vsir ingest --resume <run_id>`` then needs no path at all — it reads
``doc_id@revision`` and ``content_hash`` off the run record and resolves the bytes from the store.
The spool stays temporary and is still deleted, which is the honest arrangement: it is a transport
buffer, and the durable copy is the store's.

*It moves the spend decision to whoever can reach the port.* Ingestion bills S1, S2 and one
embedding per page, and a page-count ceiling is not a budget. So this route refuses outright when
the release is configured for a live model unless ``VSIR_ALLOW_PAID`` is set — which is also where
that variable finally becomes load-bearing: it was parsed into :class:`~vsir.config.Config` and
read by nothing, so the only real brake was a shell check in ``scripts/test-paid.sh``. There are no
token scopes in :mod:`vsir.serve.auth` yet, so this is a per-release switch and not a per-caller
one; a caller who can spend can spend everything the release allows.
"""
from __future__ import annotations

import contextlib
import os
import re
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

from vsir import logging as vsir_logging
from vsir.config import Config
from vsir.core import ids
from vsir.ingest import store as store_module
from vsir.ingest.window import MAX_INLINE_BYTES

_log = vsir_logging.get_logger(__name__)

#: The first bytes of every PDF. Checked because a content-type header is the uploader's claim and
#: this one is the file's own: handing a JPEG to PyMuPDF is a 500 from inside the child, minutes
#: later, rather than a 400 from here.
PDF_MAGIC = b"%PDF-"

#: The largest upload accepted, before the pipeline sees it. Ten times the inline part ceiling:
#: `window.inline_cap` handles a large file by shrinking the window, so size alone is not a reason
#: to refuse — but an unbounded body is a way to fill the spool, and the corpus's largest document
#: is 310 MB, so this leaves real headroom while still being a bound.
MAX_UPLOAD_BYTES = MAX_INLINE_BYTES * 10

#: Where uploads are spooled. Not one of the twelve required variables (§15 Factor III's contract
#: with `doctor`), because a release that never takes an upload must not be made unstartable by it;
#: unset means the platform's temporary directory, which is what a disposable instance has.
SPOOL_ENV = "VSIR_SPOOL_DIR"

#: The `--until` values this route will pass through. The full pipeline is the default and is safe
#: to default to: step 11 is the only thing that flips `is_current` and §11.1's gates stand in
#: front of it, so an upload that fails a blocking gate leaves nothing queryable (I7).
INGEST_UNTIL: tuple[str, ...] = ("manifest", "probe", "render", "facts", "window", "extract",
                                 "derive", "stitch", "embed", "index", "publish")


class UploadRefused(Exception):
    """A typed refusal from the upload boundary, shaped like every other one (§7.3, §11.3)."""

    def __init__(self, code: str, message: str, *, status: int = 400, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = status
        self.details = details

    def to_payload(self) -> dict[str, Any]:
        return {"error": self.code, "detail": self.message, **self.details}


@dataclass(frozen=True)
class Accepted:
    """What the caller is told: the run to poll, and where to poll it."""

    run_id: str
    doc_id: str
    revision: str
    until: str
    spooled_bytes: int

    def to_payload(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "doc_id": self.doc_id,
            "revision": self.revision,
            "until": self.until,
            "bytes": self.spooled_bytes,
            "poll": f"/runs/{self.run_id}",
            "detail": "accepted — the run is a `vsir ingest` process of this release; poll "
                      "GET /runs/{run_id} for its step, gates and state (§6.9). Nothing this run "
                      "writes is queryable until its blocking gates pass (I7, §6.7)",
        }


def spool_dir(env: Mapping[str, str] | None = None) -> Path:
    """The directory uploads are spooled into, created if it does not exist."""
    source = env if env is not None else os.environ
    configured = (source.get(SPOOL_ENV) or "").strip()
    target = Path(configured) if configured else Path(tempfile.gettempdir()) / "vsir-spool"
    target.mkdir(parents=True, exist_ok=True)
    return target


def check_spend_allowed(cfg: Config) -> None:
    """Refuse an upload that would bill a live model unless the release permits it.

    The one place ``VSIR_ALLOW_PAID`` decides anything. `stub` is free by construction — it replays
    a fixture and a miss is a typed ``fixture_miss``, never a live call (D10) — so replay-mode
    releases take uploads with no switch at all.
    """
    if cfg.vlm == "stub" or cfg.allow_paid:
        return
    raise UploadRefused(
        "spend_not_permitted",
        f"this release is configured for the live model {cfg.vlm_model!r} (VSIR_VLM={cfg.vlm}), so "
        f"an ingest bills S1, S2 and one embedding per page. VSIR_ALLOW_PAID is not set, and an "
        f"upload endpoint is not a place to discover that by accident: set it deliberately, or run "
        f"the release with VSIR_VLM=stub and a fixture",
        status=403, vlm=cfg.vlm, vlm_model=cfg.vlm_model,
    )


def check_store(cfg: Config) -> None:
    """Refuse an upload the release could never render a page image from (§4.2, U029).

    The pipeline deposits the source document at step 02 and every page raster is re-rendered from
    it on demand, so a release whose document store is missing or read-only can still ingest,
    index and publish — and every one of those pages then answers ``document_not_stored`` for its
    image, for ever. That is a `202` that quietly buys half a document, which is precisely the
    class of failure this boundary exists to convert into a status code the caller sees.

    A real write, not ``os.access``: see :meth:`~vsir.ingest.store.DocumentStore.ensure_writable`.
    """
    try:
        store_module.DocumentStore.from_config(cfg).ensure_writable()
    except store_module.StoreRefused as refusal:
        raise UploadRefused(refusal.code, str(refusal), status=503, **refusal.details) from refusal


def check_fixture(fixture: str, *, vlm: str) -> str:
    """Resolve a replay directory to an absolute path, or refuse. Returns what the child gets.

    Two bugs in one check, both found by running the thing rather than reading it.

    *Relative paths do not mean what the caller thinks.* The child's working directory is this
    process's, which is wherever the server was started — so ``data/fixtures/synthetic_3window``
    resolves against that and not against the caller's idea of the repository root. Resolving here
    makes the path unambiguous and makes the refusal name the absolute path it actually tried.

    *A missing directory used to be a doomed 202.* `stub` refuses ``vlm_backend_unavailable`` at
    step 04 — correctly, because replay mode never falls back to a live call (D10) — but step 04 is
    before the control plane exists, so the run vanished: the caller held a ``run_id`` that would
    never appear at ``/runs/{run_id}``. It is a property of the request, so it belongs here as a
    ``400`` the caller can read.

    Only checked for `stub`. A `gemini` release calls the model and may legitimately have no
    fixture; one given is where ``--record`` would write, and `cli.py` owns that.
    """
    if not fixture:
        if vlm == "stub":  # noqa: SIM102 — the two branches read better apart
            raise UploadRefused(
                "fixture_required",
                "VSIR_VLM=stub replays frozen responses by cache key and never makes a live call "
                "(D10), so it needs a fixture directory to read them from. Pass `fixture`, or set "
                "VSIR_FIXTURE on the release",
                status=400, vlm=vlm)
        return ""

    resolved = Path(fixture).expanduser().resolve()
    if not resolved.is_dir():
        raise UploadRefused(
            "fixture_not_found",
            f"the replay directory {fixture!r} resolves to {resolved} and is not a directory. A "
            f"relative path is resolved against the server's working directory, not the caller's. "
            f"Refused here rather than at step 04, because the control plane does not exist until "
            f"step 09 and a run that dies before it leaves nothing to poll",
            status=400, fixture=fixture, resolved=str(resolved))
    return str(resolved)


def check_upload(filename: str, head: bytes, size: int) -> None:
    """Everything about the bytes that can be refused before a child process is spawned."""
    if not size:
        raise UploadRefused("empty_upload", "the request carried no file bytes", status=400)
    if size > MAX_UPLOAD_BYTES:
        raise UploadRefused(
            "upload_too_large",
            f"{size:,} bytes exceeds the {MAX_UPLOAD_BYTES:,}-byte upload bound. The pipeline "
            f"itself has no such limit — `window.inline_cap` shrinks the window for a large file "
            f"— so this is a bound on the spool, not a statement about the document",
            status=413, bytes=size, limit=MAX_UPLOAD_BYTES)
    if not head.startswith(PDF_MAGIC):
        raise UploadRefused(
            "not_a_pdf",
            f"{filename or 'the upload'} does not begin with {PDF_MAGIC.decode()!r}. The file's own "
            f"first bytes are checked rather than the Content-Type header, which is the uploader's "
            f"claim: a non-PDF reaching PyMuPDF is a failure from inside the run, minutes later",
            status=415, magic=head[:8].hex())


def child_env(cfg: Config, *, vlm: str, fixture: str,
              base: Mapping[str, str] | None = None) -> dict[str, str]:
    """The child's environment: **this instance's resolved configuration**, not the process's.

    Inheriting ``os.environ`` and overriding two keys was the obvious thing and it was wrong.
    :func:`~vsir.serve.app.create_app` takes its environment as an *argument* precisely so an
    instance can be pointed at a different Qdrant or collection than the process was started with
    — that is how the API suite runs — and a child that read ``os.environ`` would ingest into the
    collection the process was launched against while its parent answered about another one. The
    run would look fine and land nowhere anyone was looking.

    So every field the pipeline reads is written back from :class:`~vsir.config.Config`, over a copy
    of the process environment for the things Config does not carry (``PATH``, ``HOME``, a proxy).
    The credential rides along unchanged: it is in the environment already and never in a log line
    or a response (§15.1).

    ``VSIR_VLM`` and ``VSIR_FIXTURE`` are the only two keys a *request* may influence, and
    :func:`check_spend_allowed` has already run against the resolved backend.
    """
    child = dict(base if base is not None else os.environ)
    child.update({
        # The twelve §15 Factor III variables. `VSIR_API_TOKENS` unconditionally, even when empty:
        # the child authenticates nobody — it is an ingest process — but its boot self-check
        # requires the variable, so omitting it would either strand the run on a named refusal or,
        # worse, let it inherit a stale value from an environment this instance is deliberately not
        # using. An empty value refuses loudly, which is the honest outcome.
        "VSIR_PORT": str(cfg.port),
        "VSIR_QDRANT_URL": cfg.qdrant_url,
        "VSIR_COLLECTION": cfg.collection,
        "VSIR_VLM_MODEL": cfg.vlm_model,
        "VSIR_EMBED_MODEL": cfg.embed_model,
        "VSIR_PROMPT_VERSION": cfg.prompt_version,
        "VSIR_API_TOKENS": ",".join(cfg.api_tokens),
        "VSIR_READ_QUOTA": str(cfg.read_quota),
        "VSIR_ALLOW_PAID": "1" if cfg.allow_paid else "0",
        "VSIR_LOG_LEVEL": cfg.log_level,
        "VSIR_RELEASE_ID": cfg.release_id,
        "VSIR_VLM": vlm or cfg.vlm,
        # And every optional one, because a default is not the same as this instance's value.
        # `VSIR_RUNS_COLLECTION` is the one that made this a bug rather than a tidiness point: the
        # child wrote its run record to the default `vsir_runs` while the app polled the collection
        # it was configured for, so `GET /runs/{run_id}` returned 404 for a run that was completing
        # perfectly well a few metres away. `VSIR_EMBED_DIM` and `VSIR_EMBED_TEXT_CHARS` are worse
        # if they drift: both are part of the §6.6 fingerprint and the D4 composition, so a
        # mismatch is a refusal to upsert, or a vector that does not mean what the collection's
        # other vectors mean.
        "VSIR_RUNS_COLLECTION": cfg.runs_collection,
        "VSIR_EMBED_DIM": str(cfg.embed_dim),
        "VSIR_EMBED_TEXT_CHARS": str(cfg.embed_text_chars),
        "VSIR_READS_PER_QUESTION": str(cfg.reads_per_question),
        "VSIR_VLM_TIER": cfg.vlm_tier,
        "VSIR_VLM_RPM": str(cfg.vlm_rpm),
        "VSIR_SAFETY_DOC_TYPES": ",".join(cfg.safety_doc_types),
        "VSIR_SAFETY_TOPICS": ",".join(cfg.safety_topics),
        # Written unconditionally, empty value included, and for the same reason as
        # `VSIR_RUNS_COLLECTION` above: an inherited value from the process environment would let
        # the child deposit the document on a volume this instance does not serve images from, so
        # every page of it would answer `document_not_stored` from a store that has it (U029).
        "VSIR_DOC_STORE": cfg.doc_store,
        "VSIR_VLM_KEY": cfg.vlm_key,
    })
    # Set, or **removed** — never merely skipped. `child` starts as a copy of this process's
    # environment, so "do not pass a fixture" cannot be expressed by not writing the key: the
    # inherited one survives. That is how a live run kept being handed the release's replay
    # directory after `accept` had already decided it should not have one, and went on failing
    # against another document's acceptance table.
    #
    # The value is already absolute and already the resolution of `fixture or cfg.fixture_dir`,
    # because `check_fixture` did both; falling back to `cfg.fixture_dir` here would put the
    # unresolved relative path back.
    if fixture:
        child["VSIR_FIXTURE"] = fixture
    else:
        child.pop("VSIR_FIXTURE", None)
    return child


def command(pdf: Path, *, run_id: str, until: str, declared: Mapping[str, str]) -> list[str]:
    """The `vsir ingest` argv this route runs — the operator's command, not a variant of it.

    Built as a list and never a shell string: a filename is caller-supplied and the only safe way
    to pass one is as an argument vector.

    ``--run-id`` carries the id minted by :func:`accept`, so the caller can poll §6.9's control
    plane before the run has done anything. **Not ``--resume``**: that continues a run which
    already exists and refuses ``run_not_found`` if it does not, so it cannot start one. The id has
    to be chosen here rather than read back out of the child, because every point of a run carries
    it (§6.7) and a caller holding a different id would be polling nothing.
    """
    argv = [sys.executable, "-m", "vsir", "ingest", str(pdf),
            "--until", until, "--run-id", run_id]
    for flag, value in (("--doc-id", declared.get("doc_id")),
                        ("--revision", declared.get("revision")),
                        ("--doc-type", declared.get("doc_type")),
                        ("--subjects", declared.get("subjects")),
                        ("--tags", declared.get("tags")),
                        ("--uploader", declared.get("uploader"))):
        if value:
            argv += [flag, value]
    return argv


def _spawn(argv: list[str], *, env: Mapping[str, str]) -> subprocess.Popen:
    """Start the ingest child. One seam, so a test can assert the argv and the environment.

    The argv and the environment are the whole of what this route decides — everything after them
    is `vsir ingest`'s — so being able to inspect them without starting a process is what makes
    them testable at L0. ``start_new_session`` detaches the child from this request's process
    group, so a client disconnect or a request timeout does not kill a run that is billing.
    """
    return subprocess.Popen(  # noqa: S603 — argv list, never a shell string
        argv, env=dict(env),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
        start_new_session=True)


def spool_name(filename: str, run_id: str) -> str:
    """The name to spool an upload under — the uploader's, sanitised, or the run id.

    **This is not cosmetic, and it is defect P4 of plan §4c.** Step 01 of the pipeline derives
    `doc_id` from the source filename and `manifest.filename_tags()` derives **tags** from it, so
    whatever this file is called becomes part of the document's identity *and* part of its `scope`
    surface (§5.3). Spooling to ``<run_id>.pdf`` therefore did two things:

    * an upload with no declared `doc_id` was published under its own run id — unfindable,
      un-scopable, and a re-upload became a *different* document, so retirement never superseded
      anything;
    * and even with `doc_id` declared, the lowercased run id was still added as a **tag** — a junk
      filter key, unique per upload, on every document the console ever ingested. Observed on
      2026-09-11 on a live run: `tags: ["01m26aj9cpjve2vcty72pcgw4q"]`.

    So the uploader's own filename is used, reduced to the characters a file name may hold. The
    fallback is the run id, for a name that survives none of that — which keeps this total, since
    a `filename` is caller-supplied and may be empty or entirely separators.
    """
    stem = Path(filename or "").stem
    safe = re.sub(r"[^A-Za-z0-9._+-]+", "-", stem).strip("-.")
    return f"{safe or run_id}.pdf"


def accept(cfg: Config, *, filename: str, body: bytes, until: str = "publish",
           vlm: str = "", fixture: str = "", declared: Mapping[str, str] | None = None,
           caller: str = "", spool: Path | None = None) -> Accepted:
    """Validate, spool, and start one `vsir ingest`. Returns as soon as the child is running.

    The ``run_id`` is minted **here** rather than read out of the child's output, so the caller has
    something to poll before the child has done anything, and so the id in the audit line is the id
    in the control plane (see :func:`command` for why it travels as ``--run-id``).

    **Everything refusable is refused before the child starts**, and that is not tidiness. §6.9's
    control plane is written from step 09 onward, because steps 01-08 need no store — so a child
    that dies at step 02 leaves *no run record at all*, and a caller who was handed ``202`` polls
    ``404`` for ever with the reason only in this process's log. Every refusal that can be decided
    from the request has to happen here, where it is a status code the caller actually sees.
    """
    if until not in INGEST_UNTIL:
        raise UploadRefused("unknown_step", f"no ingestion step {until!r}; §6.1 has "
                                            f"{list(INGEST_UNTIL)}", status=400, until=until)
    resolved_vlm = vlm or cfg.vlm
    if resolved_vlm not in ("stub", "gemini"):
        raise UploadRefused("unknown_vlm", f"no VLM backend {resolved_vlm!r} in this release",
                            status=400, vlm=resolved_vlm)
    # Order matters, and it is the caller's point of view that sets it: what they *sent* is more
    # concrete than how the release is configured, so a JPEG is `not_a_pdf` whether or not a
    # fixture is set. Spend comes before the fixture because it is the more serious refusal of the
    # two, and a caller who may not spend does not need to hear about a replay directory.
    check_upload(filename, body[:8], len(body))
    check_spend_allowed(cfg if not vlm else _with_vlm(cfg, resolved_vlm))
    # A live run inherits **no** fixture from the release, only one the request named.
    #
    # `VSIR_FIXTURE` does double duty in `cli.py`: it is where frozen responses are replayed from,
    # *and* where the run's acceptance table (`expected.json`) is read from. For a replay that is
    # one directory describing one corpus and both meanings agree. For a live ingest of an
    # arbitrary uploaded PDF neither applies — and inheriting the release's replay directory meant
    # every upload was checked against **another document's** expectations: a 4-page datasheet was
    # failing the synthetic corpus's label offset and its crop trap on page 20, reported as
    # `page_out_of_range: page 20 is outside 1..4`. The document was fine; the table was not about
    # it. Conflating the two in one variable is worth separating in `cli.py`, and is not this
    # function's to fix.
    fixture = check_fixture(fixture if resolved_vlm == "gemini" else fixture or cfg.fixture_dir,
                            vlm=resolved_vlm)
    # Last, because it is the only one of the four that is about the *release* rather than the
    # request — but still before the `202`, because a run that publishes pages nobody can ever see
    # an image of is worse than an upload that was refused.
    check_store(cfg)

    run_id = ids.run_id()
    # The uploader's name, not the run id — see :func:`spool_name` (§4c P4). Two uploads of the
    # same filename in one instance would collide, so the run id keeps them apart by directory.
    target = (spool or spool_dir()) / run_id / spool_name(filename, run_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)

    argv = command(target, run_id=run_id, until=until, declared=declared or {})
    try:
        child = _spawn(argv, env=child_env(cfg, vlm=resolved_vlm, fixture=fixture))
    except OSError as unstartable:
        target.unlink(missing_ok=True)
        raise UploadRefused(
            "ingest_unstartable",
            f"the ingest process could not be started: {type(unstartable).__name__}",
            status=500) from unstartable

    _log.info("upload_accepted", run_id=run_id, filename=filename, bytes=len(body),
              until=until, vlm=resolved_vlm, pid=child.pid, user_id=caller or "unknown",
              spool=str(target))
    _reap(child, target, run_id=run_id)
    return Accepted(run_id=run_id, doc_id=(declared or {}).get("doc_id", ""),
                    revision=(declared or {}).get("revision", ""), until=until,
                    spooled_bytes=len(body))


def _with_vlm(cfg: Config, vlm: str) -> Config:
    """`cfg` as the child will resolve it, so the spend check reads the effective backend."""
    return replace(cfg, vlm=vlm)


#: How much of a failed child's output is kept for the log line. A refusal is a handful of lines
#: at the end; the rest is the step-by-step demo text the CLI prints for a human reader.
FAILURE_TAIL_LINES = 12


def _reap(child: subprocess.Popen, spooled: Path, *, run_id: str) -> None:
    """Wait for the child in a background thread, remove its spool, and report a failure.

    A thread rather than an ``atexit`` hook or a signal handler: the spool must go when *this* run
    finishes, not when the process does, or a busy instance accumulates every PDF it was ever
    given. ``start_new_session`` means the child is not killed by a request timeout.

    **The child's output is read, not discarded.** A run that gets far enough to exist reports
    itself through §6.9's control plane, which is the designed channel and the one
    ``GET /runs/{run_id}`` reads — but a refusal *before* the run record is written has no record
    to appear in, and `DEVNULL` made those invisible: a caller saw ``202`` and then a ``run_id``
    that was never in ``vsir_runs``, with nothing anywhere saying why. Only the tail is kept, and
    only on a non-zero exit, so the success path stays quiet and the JSON stream stays JSON.
    """

    def wait() -> None:
        output = child.communicate()[0] or ""
        code = child.returncode
        spooled.unlink(missing_ok=True)
        # The upload now lives in its own `<run_id>/` directory (see `spool_name`), so removing
        # the file leaves an empty one behind — one per upload, forever, on a tmpfs.
        with contextlib.suppress(OSError):
            spooled.parent.rmdir()
        if code == 0:
            _log.info("upload_run_finished", run_id=run_id, pid=child.pid, exit_code=code)
            return
        tail = [line for line in output.splitlines() if line.strip()][-FAILURE_TAIL_LINES:]
        _log.error("upload_run_failed", run_id=run_id, pid=child.pid, exit_code=code,
                   detail="the ingest process exited non-zero; its last lines follow. A run that "
                          "reached the control plane also reports itself at GET /runs/{run_id}",
                   tail=tail)

    threading.Thread(target=wait, name=f"reap-{child.pid}", daemon=True).start()


def clear_spool(spool: Path | None = None) -> int:
    """Remove every spooled upload. For a start-up sweep after an unclean shutdown."""
    target = spool or spool_dir()
    removed = 0
    # `rglob`, because an upload is spooled as `<run_id>/<uploader's name>.pdf` — a flat glob
    # swept the old layout and would silently leave every upload of the new one behind.
    for leftover in target.rglob("*.pdf"):
        try:
            leftover.unlink()
            removed += 1
        except OSError:                                  # another instance is using the same dir
            continue
    for directory in sorted(target.glob("*/"), reverse=True):
        with contextlib.suppress(OSError):               # only if it is empty
            directory.rmdir()
    if removed:
        _log.info("spool_cleared", removed=removed, spool=str(target))
    return removed
