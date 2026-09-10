"""The recorder (§12.1, D10 · plan U013). What turns one paid ingest into a permanent fixture.

`vlm/cache.py::write` calls itself *"the generator's door, not the pipeline's"* and names its two
callers: ``python -m vsir.eval.synthetic_pdf`` at M2a, **and the one paid ingest at M2b**. The
first exists. The second is this module — without it, §12.1's *"one paid ingest buys a permanent
test corpus"* has no mechanism, and `data/fixtures/TC1E-SF/raw_window_*.json` could only be
produced by hand from a log.

It is a :class:`~vsir.vlm.client.Backend` that wraps another one and writes what it saw:

* **it never answers.** Every response comes from the wrapped backend, verbatim and unexamined —
  a recorder that could substitute a body would make the fixture a statement about itself;
* **it records the receipt, not a summary.** ``entry.body`` is frozen byte for byte under exactly
  the §6.3 key the call was made with, so replay is keyed identically and the frozen corpus can
  reproduce a truncation as a truncation (F13) rather than as a parse failure;
* **it records what it is told to and nothing else.** One directory, named on the command line for
  one run. There is no ambient "record everything" mode, because a fixture that accumulates
  responses from runs nobody meant to freeze is a fixture nobody can attribute.

**Why a wrapper rather than a step.** The pipeline makes S1 and S2 calls from two different places
and bisection makes more of them mid-flight (§6.2). A recorder wired per step would freeze the
windows a clean run produced and silently miss the ones a bisected run did — which is precisely the
run whose receipts are worth having. Wrapping the boundary catches every call by construction.

**It writes to local disk, and that is not a §15 Factor VI violation.** The fixture directory is a
build artefact of a one-off admin command that a human then commits, in the same sense as
``python -m vsir.eval.synthetic_pdf``'s output. Nothing serving reads it, no correctness depends
on it surviving the process, and the running service never records: `--record` is a flag on
`vsir ingest`, never a configuration value a deployment could carry.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vsir import logging as vsir_logging
from vsir.vlm.cache import Entry, write
from vsir.vlm.client import Backend, Request

_log = vsir_logging.get_logger(__name__)


@dataclass
class RecordingBackend:
    """Wraps a backend and freezes every response it returns into ``root``.

    Not frozen as a dataclass because :attr:`recorded` is the run's tally, and the caller reports
    it: a recorder that could not say how many receipts it kept would leave "did the fixture come
    out complete?" to a directory listing.
    """

    inner: Backend
    root: Path
    #: The paths written, in call order. One per call, including each half of a bisected window.
    recorded: list[Path] = field(default_factory=list)

    @property
    def name(self) -> str:
        """The wrapped backend's name. The recorder is not a backend anyone selects (§15 X)."""
        return getattr(self.inner, "name", "unknown")

    def generate(self, request: Request) -> Entry:
        """The wrapped backend's answer, verbatim — and a copy of it on disk.

        The write happens **after** the call returns, so a call that raised (a truncation to
        bisect, a schema-invalid body, an unreachable provider) freezes nothing: the fixture holds
        responses the pipeline accepted, and §6.2's repair re-bills into a fresh key of its own.
        """
        entry = self.inner.generate(request)
        # `usage` and `finish_reason` are the register B1 provenance sidecar and the two fields
        # `FixtureStore.get` reads back, so a replayed call reports the same token counts and the
        # same truncation as the call that was billed.
        meta: dict[str, object] = {
            "namespace": request.namespace, "key": request.key, "stage": request.stage,
            "label": request.label, "origin": entry.origin,
            "finish_reason": entry.finish_reason, "images": len(request.images),
            "bytes": len(entry.body),
        }
        if entry.usage:
            meta["usage"] = dict(entry.usage)
        path = write(self.root, request.namespace, request.key, entry.body, meta=meta)
        self.recorded.append(path)
        _log.info("vlm_recorded", stage=request.stage, namespace=request.namespace,
                  cache_key=request.key, path=str(path), bytes=len(entry.body),
                  origin=entry.origin, label=request.label)
        return entry


def recording(inner: Backend, root: str | Path) -> RecordingBackend:
    """Wrap ``inner`` so every response it gives is frozen under ``root``."""
    return RecordingBackend(inner=inner, root=Path(root))


def freeze_text(root: str | Path, probed: Any) -> Path:
    """Write §12.1's ``text.json`` — the extractor's output, page by page, beside the receipts.

    It is here rather than in `ingest/probe.py` for the same reason :func:`write` is not a
    :class:`~vsir.vlm.cache.FixtureStore` method: the probe's job is to read a PDF, and freezing an
    artefact for a corpus is the recorder's. It is here rather than in the CLI so that what a
    fixture directory contains is decided in one module.

    The file carries ``probe_version`` and ``content_hash`` with the text. Without them a
    ``text.json`` is a wall of prose nobody can attribute: §12.1 pins the extractor, and a fixture
    that cannot say which extractor produced it cannot prove it still matches the PDF it came
    from — which is precisely R3's failure mode, seen from the test suite instead of the index.
    """
    destination = Path(root) / "text.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps({
        "probe_version": probed.probe_version,
        "content_hash": probed.content_hash,
        "page_count": probed.page_count,
        "pages": [{"page_no": page.page_no, "text": page.text, "label": page.label}
                  for page in probed.pages],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _log.info("text_recorded", path=str(destination), pages=probed.page_count,
              probe_version=probed.probe_version)
    return destination


__all__ = ["RecordingBackend", "freeze_text", "recording"]
