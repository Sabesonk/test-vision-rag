"""The append-only audit line (Spec §7.4). Net new — `impl` recorded nothing about who spent what.

Exactly one line per `read` and per `fetch`, carrying exactly ten fields:

    user_id · run_id · session_id · tool · page_ids · dpi · input_tokens · output_tokens ·
    cache_hit · latency_ms

**Cost goes here, not into the response body.** The agent gets one integer, ``reads_remaining``.
§7.4 is explicit about why: *"a `usd_estimate` beside the verification stamps is noise next to the
fields that must not be missed"* — a model reading its own bill next to a `present`/`absent`
verdict is a model with a reason to stop reading. The operator's question (*"who spent this, on
which pages, and did the cache save it?"*) and the agent's question (*"how many reads have I
left?"*) are different questions, and they get different channels.

**Only the two tools that consume something are audited.** A `lookup`, a `skim` or a `verify` is
free and emits no line: a line per free call would bury the ten-field records that matter under
the traffic of the tools that cost nothing, and §11.4 asks for nothing per call from a free tool.
The free tools still log — at ``debug``, with their own fields — so the event stream is not silent
about them; they are simply not *audit*.

**The schema is exactly ten fields and :func:`emit` refuses an eleventh.** §15.1's retention row:
*"never widen the audit schema with document content."* An audit stream carrying page text is a
copy of the corpus in the log aggregator, with the retention policy of a log aggregator; carrying
a question is a copy of what the operator asked. Both are one well-meaning `**extra` away, so the
assertion is in the constructor rather than in a review checklist.

**The line is nested under one ``audit`` key, not spread across the log record.** Two reasons, and
the first is not cosmetic: `logging.redact` blanks any field whose *name* looks credential-shaped,
and ``token`` is one of its hints — so a top-level ``input_tokens`` would arrive on the stream as
``***``. That is the redactor working correctly on a name that has nothing to do with a secret.
Nesting also makes *"exactly ten fields"* something a test can assert directly on one object,
rather than by subtracting the log envelope's own keys.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

from vsir import logging as vsir_logging

#: The event name every audit line carries. One name, so a log query is `event = "audit"`.
AUDIT_EVENT = "audit"

#: The key the ten fields hang off. See the module docstring: `input_tokens` at the top level
#: would be redacted by name.
AUDIT_KEY = "audit"

#: §7.4, in order. The tuple is the contract: :class:`AuditLine` is asserted against it at import.
AUDIT_FIELDS: tuple[str, ...] = (
    "user_id", "run_id", "session_id", "tool", "page_ids", "dpi",
    "input_tokens", "output_tokens", "cache_hit", "latency_ms",
)

#: The tools that consume something and are therefore audited (§7.4). `read` spends model tokens;
#: `fetch` spends render time and megapixels. Everything else in §7.2 is free and emits no line.
AUDITED_TOOLS: frozenset[str] = frozenset({"read", "fetch"})

_log = vsir_logging.get_logger(__name__)


@dataclass(frozen=True)
class Usage:
    """What a tool consumed, reported back by the tool for the audit line.

    A free tool returns :meth:`free` and the dispatcher emits nothing. A paid one fills in what it
    actually used, which is why ``cache_hit`` is here: a replayed `read` costs nothing and the
    audit line is the only place that distinction is recorded (§6.3, F11).
    """

    page_ids: tuple[str, ...] = ()
    dpi: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_hit: bool = False

    @classmethod
    def free(cls) -> "Usage":
        """A tool that consumed nothing. Not audited, and the zeroes are never written anywhere."""
        return cls()


class AuditLine(BaseModel):
    """The ten fields of §7.4, and nothing else. ``extra="forbid"`` is the retention guard."""

    model_config = ConfigDict(extra="forbid")

    user_id: str
    run_id: str = ""
    session_id: str = ""
    tool: str
    page_ids: list[str] = Field(default_factory=list)
    dpi: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_hit: bool = False
    latency_ms: int = 0


# The schema and the spec's list are checked against each other at import, not in a test: a field
# added to the model without adding it to §7.4's tuple is a widening of an append-only audit
# schema, and it should fail where it is written rather than three suites later. A raise rather
# than an `assert`, for the same reason I5's validator is one — `python -O` strips asserts, and a
# retention guard that a flag can remove is not a guard.
if tuple(AuditLine.model_fields) != AUDIT_FIELDS:
    raise RuntimeError(
        f"the audit schema is §7.4's ten fields exactly, in order: {AUDIT_FIELDS}; "
        f"AuditLine declares {tuple(AuditLine.model_fields)}"
    )


@dataclass
class Timer:
    """Wall-clock milliseconds around one tool call — the audit line's ``latency_ms``.

    ``perf_counter`` rather than ``time.time``: a clock step (an NTP correction, a leap second)
    must not turn a 30 ms call into a negative number in the one record that says what the call
    cost.
    """

    started: float = field(default_factory=time.perf_counter)

    @property
    def elapsed_ms(self) -> int:
        return max(0, round((time.perf_counter() - self.started) * 1000))


def line(*, user_id: str, tool: str, usage: Usage, latency_ms: int,
         run_id: str = "", session_id: str = "") -> AuditLine:
    """Build the record. Separate from :func:`emit` so a test can assert the shape without a log."""
    return AuditLine(
        user_id=user_id,
        run_id=run_id,
        session_id=session_id,
        tool=tool,
        page_ids=list(usage.page_ids),
        dpi=usage.dpi,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_hit=usage.cache_hit,
        latency_ms=latency_ms,
    )


def audited(tool: str) -> bool:
    """Whether this tool emits an audit line at all (§7.4: `read` and `fetch`, nothing else)."""
    return tool in AUDITED_TOOLS


def emit(record: AuditLine) -> AuditLine:
    """Write the one line, to stdout, as JSON (§15 Factor XI).

    ``info``, not ``debug``: this is the record an operator must be able to find, and a level a
    deployment might raise past would make the audit trail depend on ``VSIR_LOG_LEVEL``. There is
    no file, no rotation and no shipping — the platform collects stdout, and *that* is the
    append-only medium. An audit log the application manages is an audit log the application can
    truncate.
    """
    _log.info(AUDIT_EVENT, **{AUDIT_KEY: record.model_dump(mode="json")})
    return record


def fields_of(payload: Mapping[str, Any]) -> Iterator[str]:
    """The audit field names in a parsed log line — what a test asserts *exactly ten* against."""
    return iter(payload.get(AUDIT_KEY, {}))


def page_ids_of(page_ids: Sequence[str] | None) -> tuple[str, ...]:
    """Normalise a tool's page list for :class:`Usage`, dropping empties, order preserved."""
    return tuple(str(page_id) for page_id in (page_ids or ()) if page_id)
