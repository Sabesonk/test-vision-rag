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
literally true for that window. The consequence is concrete and is disclosed rather than papered
over: a run started by upload is **not resumable across an instance restart**, because
``vsir ingest --resume`` needs the source PDF and the spool went with the instance. A run started
from the CLI is resumable, because the operator's copy is still on their filesystem. The spool is
removed when the child exits, however it exits.

*It moves the spend decision to whoever can reach the port.* Ingestion bills S1, S2 and one
embedding per page, and a page-count ceiling is not a budget. So this route refuses outright when
the release is configured for a live model unless ``VSIR_ALLOW_PAID`` is set — which is also where
that variable finally becomes load-bearing: it was parsed into :class:`~vsir.config.Config` and
read by nothing, so the only real brake was a shell check in ``scripts/test-paid.sh``. There are no
token scopes in :mod:`vsir.serve.auth` yet, so this is a per-release switch and not a per-caller
one; a caller who can spend can spend everything the release allows.
"""
from __future__ import annotations

import os
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
        "VSIR_PORT": str(cfg.port),
        "VSIR_QDRANT_URL": cfg.qdrant_url,
        "VSIR_COLLECTION": cfg.collection,
        "VSIR_VLM_MODEL": cfg.vlm_model,
        "VSIR_EMBED_MODEL": cfg.embed_model,
        "VSIR_PROMPT_VERSION": cfg.prompt_version,
        "VSIR_READ_QUOTA": str(cfg.read_quota),
        "VSIR_ALLOW_PAID": "1" if cfg.allow_paid else "0",
        "VSIR_LOG_LEVEL": cfg.log_level,
        "VSIR_RELEASE_ID": cfg.release_id,
        "VSIR_VLM": vlm or cfg.vlm,
        # Unconditionally, even when empty. The child does not authenticate anyone — it is an
        # ingest process — but ``VSIR_API_TOKENS`` is one of the twelve §15 Factor III variables
        # its boot self-check requires, so omitting it would either strand the run on a named
        # refusal or, worse, let it inherit a stale value from a process environment this instance
        # is deliberately not using. An empty value refuses loudly, which is the honest outcome.
        "VSIR_API_TOKENS": ",".join(cfg.api_tokens),
    })
    if fixture or cfg.fixture_dir:
        child["VSIR_FIXTURE"] = fixture or cfg.fixture_dir
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


def accept(cfg: Config, *, filename: str, body: bytes, until: str = "publish",
           vlm: str = "", fixture: str = "", declared: Mapping[str, str] | None = None,
           caller: str = "", spool: Path | None = None) -> Accepted:
    """Validate, spool, and start one `vsir ingest`. Returns as soon as the child is running.

    The ``run_id`` is minted **here** rather than read out of the child's output, so the caller has
    something to poll before the child has done anything, and so the id in the audit line is the id
    in the control plane. `cli.py` accepts it through ``--resume``, whose contract is exactly
    *"continue under this id"* — a fresh run under a chosen id is the same operation with no prior
    state, and it is why that flag keeps the id rather than minting one (§6.7).
    """
    if until not in INGEST_UNTIL:
        raise UploadRefused("unknown_step", f"no ingestion step {until!r}; §6.1 has "
                                            f"{list(INGEST_UNTIL)}", status=400, until=until)
    resolved_vlm = vlm or cfg.vlm
    if resolved_vlm not in ("stub", "gemini"):
        raise UploadRefused("unknown_vlm", f"no VLM backend {resolved_vlm!r} in this release",
                            status=400, vlm=resolved_vlm)
    check_spend_allowed(cfg if not vlm else _with_vlm(cfg, resolved_vlm))
    check_upload(filename, body[:8], len(body))

    run_id = ids.run_id()
    target = (spool or spool_dir()) / f"{run_id}.pdf"
    target.write_bytes(body)

    argv = command(target, run_id=run_id, until=until, declared=declared or {})
    try:
        child = subprocess.Popen(  # noqa: S603 — argv list, never a shell string
            argv, env=child_env(cfg, vlm=resolved_vlm, fixture=fixture),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
            start_new_session=True)
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
    for leftover in target.glob("*.pdf"):
        try:
            leftover.unlink()
            removed += 1
        except OSError:                                  # another instance is using the same dir
            continue
    if removed:
        _log.info("spool_cleared", removed=removed, spool=str(target))
    return removed
