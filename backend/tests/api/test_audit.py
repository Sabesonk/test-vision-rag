"""L2 — one append-only audit line per `read` and per `fetch`, and cost nowhere else (Spec §7.4).

Ten fields, exactly: ``user_id · run_id · session_id · tool · page_ids · dpi · input_tokens ·
output_tokens · cache_hit · latency_ms``. The operator's question — *who spent this, on which
pages, and did the cache save it?* — and the agent's question — *how many reads have I left?* —
are different questions and get different channels. The agent gets one integer,
``reads_remaining``; everything about money is on the event stream.

**Why the two spending tools are spies here.** `read` is U020's and `fetch` is U018's; what U014
owns is the *policy* — which tools are audited, what the line contains, where identity comes from
and that a free tool emits nothing. So the suite registers tools into ``app.state.tools``, which
is the same extension point the real ones will use, and asserts the dispatcher's behaviour around
them. It is not a test-only branch in the production path (§15.2): no code under `backend/vsir/`
knows this suite exists, and the table is per-app precisely so a test can hold its own.

When U018 and U020 land, their suites assert the same lines for the real tools; these keep
asserting that the *rule* holds for anything registered as spending.
"""
from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict, Field

from vsir.config import DPI_ANSWER
from vsir.serve import app as app_module
from vsir.serve import audit as audit_module
from vsir.serve import auth as auth_module
from vsir.serve.audit import AUDIT_FIELDS, AUDIT_KEY, AuditLine, Usage
from vsir.serve.envelope import Provenance, ToolEnvelope

from conftest import TEST_TOKEN, log_events

LOOKUP = "/tools/lookup"
PAGES = ["SYN-M1@1.0#p001", "SYN-M1@1.0#p002"]

#: Field names that must never appear anywhere in a response body (§7.4). `reads_remaining` is
#: the one number about consumption the caller gets, and it is a budget, not a bill.
BANNED_IN_A_BODY = ("usd", "cost", "price", "dollar", "input_tokens", "output_tokens",
                    "token_count", "tokens_used", "spend", "billing")


class SpyResult(BaseModel):
    """Stands in for `ReadResult`/`FetchResult` — Family B's ``result`` half (§7.1)."""

    model_config = ConfigDict(extra="forbid")

    pages: list[str] = Field(default_factory=list)


class SpyRequest(app_module.ToolRequest):
    page_ids: list[str] = Field(default_factory=list)
    question: str = ""


def _spy_call(usage: Usage):
    def call(context: app_module.ToolContext, body: SpyRequest):
        envelope = ToolEnvelope[SpyResult](
            status="ok", result=SpyResult(pages=list(body.page_ids)),
            provenance=Provenance(release_id=context.cfg.release_id))
        return envelope, usage
    return call


def _register(client, name: str, *, spends: bool, usage: Usage | None = None) -> None:
    """Put a tool in this app's table. Per-app by construction, so nothing leaks between tests."""
    consumed = usage if usage is not None else Usage(
        page_ids=tuple(PAGES), dpi=DPI_ANSWER, input_tokens=4210, output_tokens=138,
        cache_hit=False)
    client.app.state.tools[name] = app_module.ToolSpec(
        name=name, request=SpyRequest, call=_spy_call(consumed), spends=spends)


def _audit_lines(buffer) -> list[dict]:
    return [event[AUDIT_KEY] for event in log_events(buffer) if event["event"] == "audit"]


# ── exactly one line, exactly ten fields ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("tool,spends", [("read", True), ("fetch", False)])
def test_a_spending_tool_emits_exactly_one_audit_line(served, token_header, log_stream,
                                                      tool, spends):
    """§7.4 — one line per `read` and per `fetch`. One, not zero and not two."""
    _register(served, tool, spends=spends)

    response = served.post(f"/tools/{tool}", json={"page_ids": PAGES, "question": "why?"},
                           headers=token_header)

    assert response.status_code == 200, response.text
    lines = _audit_lines(log_stream)
    assert len(lines) == 1, log_stream.getvalue()
    assert lines[0]["tool"] == tool


def test_the_audit_line_carries_all_ten_fields_and_no_eleventh(served, token_header, log_stream):
    """§15.1's retention row — *never widen the audit schema with document content.*"""
    _register(served, "read", spends=True)

    served.post("/tools/read", json={"page_ids": PAGES, "question": "what resets K158?"},
                headers=token_header)

    line = _audit_lines(log_stream)[0]
    # The *set* on the wire, because the JSON formatter sorts keys so a collector's diff is
    # stable; the *order* on the model, which is where §7.4's list is actually pinned.
    assert set(line) == set(AUDIT_FIELDS)
    assert len(line) == len(AUDIT_FIELDS) == 10
    assert tuple(AuditLine.model_fields) == AUDIT_FIELDS
    assert line["page_ids"] == PAGES
    assert line["dpi"] == DPI_ANSWER
    assert line["input_tokens"] == 4210
    assert line["output_tokens"] == 138
    assert line["cache_hit"] is False
    assert isinstance(line["latency_ms"], int) and line["latency_ms"] >= 0


def test_the_audit_line_never_carries_the_question_or_the_page_text(served, token_header,
                                                                    log_stream):
    """A question is what the operator asked; an audit stream is not the place to keep a copy."""
    _register(served, "read", spends=True)
    question = "what resets K158 after an emergency stop"

    served.post("/tools/read", json={"page_ids": PAGES, "question": question},
                headers=token_header)

    assert question not in str(_audit_lines(log_stream)[0])


def test_the_audit_schema_refuses_an_extra_field():
    """The guard is in the model, not in a review checklist: one `**extra` is all it would take."""
    with pytest.raises(Exception):
        AuditLine(user_id="caller-x", tool="read", page_text="B221 --> K158")


def test_a_cache_hit_is_recorded_as_one(served, token_header, log_stream):
    """A replayed `read` costs nothing, and the audit line is the only place that is recorded."""
    _register(served, "read", spends=True,
              usage=Usage(page_ids=tuple(PAGES), dpi=DPI_ANSWER, cache_hit=True))

    served.post("/tools/read", json={"page_ids": PAGES}, headers=token_header)

    line = _audit_lines(log_stream)[0]
    assert line["cache_hit"] is True
    assert line["input_tokens"] == 0


# ── a free tool is not audited ───────────────────────────────────────────────────────────────────

def test_a_lookup_emits_no_audit_line(served, token_header, corpus, log_stream):
    """§7.4 audits the two tools that consume something. A line per free call would bury them."""
    response = served.post(LOOKUP, headers=token_header,
                           json={"label": corpus.expected["compact_labels"][0]["label"]})

    assert response.status_code == 200
    assert _audit_lines(log_stream) == []
    # …and it is not silent either: the free tools log at `debug`, with their own fields.
    assert [event for event in log_events(log_stream) if event["event"] == "lookup"]


def test_the_audited_set_is_exactly_read_and_fetch():
    assert audit_module.AUDITED_TOOLS == {"read", "fetch"}
    assert audit_module.audited("read") and audit_module.audited("fetch")
    assert not any(audit_module.audited(free)
                   for free in ("lookup", "verify", "resolve", "skim_pages", "skim_sections",
                                "skim_documents"))


# ── identity on the line comes from the token ────────────────────────────────────────────────────

def test_the_audit_line_records_the_tokens_identity_not_the_clients(served, token_header,
                                                                    log_stream):
    """§7.4's acceptance criterion, asserted where it matters: on the audit line itself.

    Two identical `read` calls, one of which claims to be ``root``. The recorded ``user_id`` is
    the same digest both times — because a caller who could name themselves in the log that says
    who spent the money could name somebody else.
    """
    _register(served, "read", spends=True)

    served.post("/tools/read", json={"page_ids": PAGES}, headers=token_header)
    served.post("/tools/read", json={"page_ids": PAGES},
                headers={**token_header, "X-User-Id": "root"})

    honest, claimed = _audit_lines(log_stream)
    assert honest["user_id"] == claimed["user_id"] == auth_module.caller_id(TEST_TOKEN)
    assert "root" not in str(claimed)


def test_the_audit_line_carries_the_correlation_ids_the_caller_supplied(served, token_header,
                                                                        log_stream):
    """``run_id`` and ``session_id`` are correlation, not identity — so the caller may set them."""
    _register(served, "read", spends=True)

    served.post("/tools/read", json={"page_ids": PAGES},
                headers={**token_header, "X-Session-Id": "sess-77", "X-Run-Id": "run-9"})

    line = _audit_lines(log_stream)[0]
    assert line["session_id"] == "sess-77"
    assert line["run_id"] == "run-9"


def test_every_line_of_the_request_shares_one_request_id(served, token_header, log_stream):
    """§11.4 — correlation survives the hop into the worker thread the sync tool runs in."""
    _register(served, "read", spends=True)

    served.post("/tools/read", json={"page_ids": PAGES}, headers=token_header)

    request_ids = {event["request_id"] for event in log_events(log_stream)
                   if "request_id" in event}
    assert len(request_ids) == 1, log_events(log_stream)
    assert [event for event in log_events(log_stream)
            if event["event"] == "audit" and "request_id" in event]


# ── the audit line survives the log redactor ─────────────────────────────────────────────────────

def test_the_token_counts_are_not_blanked_by_the_credential_redactor(served, token_header,
                                                                     log_stream):
    """`logging.redact` blanks any field whose *name* looks credential-shaped, and `token` is one.

    A top-level ``input_tokens`` would arrive as ``***`` — the redactor working correctly on a
    name that has nothing to do with a secret. Nesting the ten fields under one key is what keeps
    §7.4's schema intact, and this is the test that says so rather than a comment.
    """
    _register(served, "read", spends=True)

    served.post("/tools/read", json={"page_ids": PAGES}, headers=token_header)

    line = _audit_lines(log_stream)[0]
    assert line["input_tokens"] == 4210
    assert line["output_tokens"] == 138


# ── cost never reaches the response body ─────────────────────────────────────────────────────────

def _keys(node, found: list[str]) -> list[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            found.append(key)
            _keys(value, found)
    elif isinstance(node, list):
        for value in node:
            _keys(value, found)
    return found


@pytest.mark.parametrize("tool", ["lookup", "read", "fetch"])
def test_no_response_body_carries_a_cost_a_token_count_or_a_usd_estimate(served, token_header,
                                                                         corpus, tool):
    """§7.4 — *cost goes in the audit log, not the response body.*"""
    if tool == "lookup":
        body = {"label": corpus.expected["compact_labels"][0]["label"]}
    else:
        _register(served, tool, spends=(tool == "read"))
        body = {"page_ids": PAGES}

    response = served.post(f"/tools/{tool}", json=body, headers=token_header)

    assert response.status_code == 200, response.text
    offenders = [key for key in _keys(response.json(), [])
                 if any(banned in key.lower() for banned in BANNED_IN_A_BODY)]
    assert not offenders


@pytest.mark.parametrize("tool", ["lookup", "read", "fetch"])
def test_reads_remaining_is_an_integer_on_every_envelope(served, token_header, corpus, tool):
    """§7.1 — on **every** envelope, both families, stamped by the dispatcher so none can forget."""
    if tool == "lookup":
        body = {"label": corpus.expected["compact_labels"][0]["label"]}
    else:
        _register(served, tool, spends=(tool == "read"))
        body = {"page_ids": PAGES}

    payload = served.post(f"/tools/{tool}", json=body, headers=token_header).json()

    assert isinstance(payload["reads_remaining"], int)
    assert payload["reads_remaining"] >= 0
