"""Structured JSON logs, one event per line, on stdout (Spec §15 Factor XI).

The app never opens a log file, never rotates and never ships logs itself: stdout is the stream and
the platform collects it. Every line carries ``release_id`` and ``level``; ``run_id``,
``session_id``, ``request_id`` and ``tool`` ride along from the correlation context whenever the
caller has entered one, which is what makes an answer traceable back to the run and the call that
produced it (§11.4).

The correlation context is a :class:`~contextvars.ContextVar` holding nothing but those four ids.
It is deliberately *not* a session store: no retrieval result, no scope and no page ever enters it
(C11, §15.2). Values set inside a task do not leak into a sibling task, so a concurrent request
cannot borrow another's ``request_id``.
"""
from __future__ import annotations

import contextvars
import json
import logging
import sys
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Mapping

CORRELATION_KEYS = ("run_id", "session_id", "request_id", "tool")
REDACTED = "***"

# A field is redacted on its *name*, so a new call site cannot leak a credential by forgetting to.
# `Bearer`, the API tokens and the VLM key must never appear in a log line (§15.1).
_REDACT_HINTS = ("token", "secret", "password", "authorization", "credential", "bearer")
_REDACT_EXACT = frozenset({"key", "vlm_key", "auth"})

_correlation: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar(
    "vsir_correlation", default=None
)

_LINE_BREAKS = str.maketrans({"\u2028": " ", "\u2029": " "})


def correlation() -> dict[str, str]:
    """The correlation ids in force for this task, or an empty mapping."""
    return dict(_correlation.get() or {})


@contextmanager
def correlate(**ids: str | None) -> Iterator[None]:
    """Bind correlation ids for the duration of the block.

    Unknown keys are refused rather than silently logged: the four of ``CORRELATION_KEYS`` are the
    correlation contract, and a typo'd id is a broken audit trail.
    """
    unknown = sorted(set(ids) - set(CORRELATION_KEYS))
    if unknown:
        raise ValueError(f"not a correlation id: {unknown} (expected {list(CORRELATION_KEYS)})")
    merged = correlation()
    merged.update({k: str(v) for k, v in ids.items() if v is not None})
    reset = _correlation.set(merged)
    try:
        yield
    finally:
        _correlation.reset(reset)


def redact(fields: Mapping[str, Any]) -> dict[str, Any]:
    """Replace the value of any credential-shaped field name with ``***``."""
    out: dict[str, Any] = {}
    for name, value in fields.items():
        lowered = name.lower()
        if lowered in _REDACT_EXACT or any(hint in lowered for hint in _REDACT_HINTS):
            out[name] = REDACTED
        else:
            out[name] = value
    return out


class JsonFormatter(logging.Formatter):
    """One JSON object per record, with the envelope keys always present and always authoritative."""

    def __init__(self, release_id: str) -> None:
        super().__init__()
        self.release_id = release_id

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003 - logging's own name
        payload: dict[str, Any] = {}
        payload.update(redact(getattr(record, "fields", None) or {}))
        payload.update(correlation())
        # The envelope is written last: a caller's field can never shadow it.
        payload["ts"] = datetime.fromtimestamp(record.created, timezone.utc).isoformat(
            timespec="milliseconds"
        )
        payload["level"] = record.levelname.lower()
        payload["release_id"] = self.release_id
        payload["logger"] = record.name
        payload["event"] = record.getMessage()
        if record.exc_info:
            exc_type, exc, tb = record.exc_info
            payload["error"] = {
                "type": getattr(exc_type, "__name__", str(exc_type)),
                "message": str(exc),
                "traceback": "".join(traceback.format_exception(exc_type, exc, tb)).strip(),
            }
        line = json.dumps(payload, default=str, sort_keys=True, ensure_ascii=False)
        # One event per line is the contract (§15 Factor XI). json.dumps escapes \n and \r, but
        # leaves the two Unicode line separators alone, and a collector may split on them.
        return line.translate(_LINE_BREAKS)


def configure(*, release_id: str, level: str = "INFO", stream: Any | None = None) -> None:
    """Install the one handler this process logs through. Safe to call more than once.

    An unrecognised ``level`` falls back to ``INFO`` rather than raising: the boot self-check is
    what reports a bad ``VSIR_LOG_LEVEL`` (§4.3), and it needs a working logger to report it with.
    """
    handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
    handler.setFormatter(JsonFormatter(release_id=release_id or "unknown"))
    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(logging.getLevelNamesMapping().get((level or "").upper(), logging.INFO))


class EventLogger:
    """A logger whose calls are events with fields, not formatted sentences."""

    __slots__ = ("_log",)

    def __init__(self, name: str) -> None:
        self._log = logging.getLogger(name)

    # `event` is positional-only throughout, and the fields travel as a mapping: a payload key
    # called `event`, `level` or `exc_info` is ordinary data and must not collide with the
    # signature. The formatter is what keeps the envelope authoritative.
    def _emit(self, level: int, event: str, fields: dict[str, Any], /, exc_info: bool = False) -> None:
        self._log.log(level, event, exc_info=exc_info, extra={"fields": fields})

    def debug(self, event: str, /, **fields: Any) -> None:
        self._emit(logging.DEBUG, event, fields)

    def info(self, event: str, /, **fields: Any) -> None:
        self._emit(logging.INFO, event, fields)

    def warning(self, event: str, /, **fields: Any) -> None:
        self._emit(logging.WARNING, event, fields)

    def error(self, event: str, /, **fields: Any) -> None:
        self._emit(logging.ERROR, event, fields)

    def exception(self, event: str, /, **fields: Any) -> None:
        self._emit(logging.ERROR, event, fields, exc_info=True)


def get_logger(name: str) -> EventLogger:
    """The logger for a module: ``get_logger(__name__)``."""
    return EventLogger(name)
