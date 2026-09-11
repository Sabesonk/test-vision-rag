"""L2/L3 — `POST /ask` end to end over a really ingested document, for nothing (§8, D10).

The whole product, in replay. Every row here drives the shipped surface — the route, the bearer
middleware, the dispatcher, the budget, the three skim rungs, the document store, the renderer at
the pinned dpi, `read`'s frozen response and the gate's real `verify` calls — and the only thing
standing in for Gemini is a response frozen under exactly the §6.3 key the call is made with,
which is production's own code path with a different attached service (§15 Factor IV, X).

**Nothing below computes what it asserts.** The questions and the expected codes come out of
`data/fixtures/synthetic_3window/expected.json`, written beside the frozen responses before the
loop existed. C10's rule applies to a stamp exactly as it applies to a page count: a number a test
derives from the code under test cannot fail, it can only re-baseline itself.

The one thing to understand about the fixtures to read this suite: **each question names a printed
code**, so the loop's handle branch (*"handle? yes → lookup"*, §8.1) settles which pages are read
from the exact surface rather than from a dense ranking. `K119` is printed on page 19 and nowhere
else, so *"…when K119 is monitored"* pins one page, on every machine and in every ordering — which
is what makes a frozen `read` reachable from a whole-loop test at all.
"""
from __future__ import annotations

import json
import socket
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient

from vsir.eval.synthetic_pdf import (
    ASK_ANSWER_QUESTION,
    ASK_LADDER_QUESTION,
    ASK_REJECTED_QUESTION,
)
from vsir.runner.answer import BADGE_READ_FROM_IMAGE, BADGE_VERIFIED, FORBIDDEN_WORDING
from vsir.serve.app import create_app

from conftest import TEST_TOKEN, log_events

REPO = Path(__file__).resolve().parents[3]
EXPECTED = json.loads(
    (REPO / "data/fixtures/synthetic_3window/expected.json").read_text(encoding="utf-8"))
CASES = EXPECTED["read"]["cases"]

#: Nothing listens here, and nothing may start to — the mid-loop outage of §11.3 row 1.
UNREACHABLE_URL = "http://127.0.0.1:6399"


def case(name: str) -> dict:
    return CASES[name]


@contextmanager
def variant(asking: Any, qdrant: Any, **overrides: str) -> Iterator[Any]:
    """A third app over the same ingested corpus, with its own configuration and its own ledger.

    Its own runs collection again, because a suite that exhausts a per-question budget must not
    exhaust the caller quota for the next one — the same reason `test_read_caps.py` builds its own
    instance for the read cap, and the reason `asking` exists at all.
    """
    runs = f"{asking.env['VSIR_RUNS_COLLECTION']}_{abs(hash(tuple(sorted(overrides.items()))))}"
    env = {**asking.env, **overrides, "VSIR_RUNS_COLLECTION": runs}
    try:
        with TestClient(create_app(env)) as client:
            yield client
    finally:
        if qdrant.collection_exists(runs):
            qdrant.delete_collection(runs)


def ask(client: Any, question: str, **arguments: Any) -> Any:
    """One question over the route, for the variant apps that have no :class:`AskStack`."""
    return client.post("/ask", headers={"Authorization": f"Bearer {TEST_TOKEN}"},
                       json={"question": question, **arguments})


# ── the worked trace (§13 M6's acceptance) ──────────────────────────────────────────────────────

def test_the_worked_trace_answers_in_exactly_one_paid_read(asking: Any):
    """§13 M6: *"the loop completes in **exactly one paid `read`**"*, and the answer is gated.

    One question, one `lookup` on the code it names, one triage, one `read`, one draft, one gate.
    The read count is read off the response and cross-checked against the moves that declared
    themselves as spending — the trace is the call log, so *"exactly one"* is an observation and
    not an assertion about intent.
    """
    row = case("ask_answer")
    response = asking.ask(ASK_ANSWER_QUESTION)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "answered"
    assert payload["reads"] == 1, payload["trace"]
    assert [move["action"] for move in payload["trace"] if move["spends"]] == ["read"]
    assert payload["route"] == "read", (
        "the runner is Python holding an envelope: it cannot look at a raster, so §8.1a's "
        "delegation route is the one that applies (§8.1a)")
    assert payload["answer"]["citations"] == asking.page_ids(*row["pages"])
    assert payload["answer"]["text"] == row["extract"], (
        "the sub-model's own words, rendered and never rewritten (§7.6)")


def test_every_code_in_the_answer_is_badged_and_was_checked_against_its_cited_page(asking: Any):
    """I8, asserted by the call log rather than by reading the prose.

    For every rendered code there is a `(claim, page)` row in ``checks`` — one `verify` call the
    gate really made — and the page on the badge is the page in the call.
    """
    row = case("ask_answer")
    payload = asking.ask(ASK_ANSWER_QUESTION).json()

    claims = payload["answer"]["claims"]
    assert [one["code"] for one in claims] == row["codes"], (
        "in the order the model emitted them, verbatim: the gate reorders nothing")
    assert {one["badge"] for one in claims} == {BADGE_VERIFIED}
    checked = {(row_["claim"], row_["page_id"]) for row_ in payload["checks"] if row_["claim"]}
    for claim in claims:
        assert (claim["code"], claim["page_id"]) in checked, (claim, payload["checks"])
    assert all(stamp["status"] == "present" for stamp in row["stamps"]), (
        "the fixture's own acceptance table says every code of this case is printed on page 19")


def test_the_read_call_count_is_one_in_the_audit_log_too(asking: Any, log_stream: Any):
    """The other spy: §7.4's audit line, which is written once per `read` and per `fetch`.

    A count the loop reports about itself and a count the audit ledger reports about the process
    are two independent observations, and the money is in the second one.
    """
    asking.ask(ASK_ANSWER_QUESTION)

    audited = [event for event in log_events(log_stream)
               if event.get("event") == "audit" and event.get("tool") == "read"]
    assert len(audited) == 1, [event.get("event") for event in log_events(log_stream)]


def test_the_trace_shows_the_moves_of_8_1_in_order(asking: Any):
    """*"descend → triage → look → draft → verify"* — §8.1's diagram, as a record of what ran.

    The order is the invariant, not the wording: **the expensive step happens after the free
    narrowing, and the verification happens after the drafting.** A trace with `verify` before
    `draft` would be a gate that cannot catch anything.
    """
    payload = asking.ask(ASK_ANSWER_QUESTION).json()
    states = [move["state"] for move in payload["trace"]]

    assert states == ["descend", "triage", "look", "look", "draft", "verify"], states
    assert states.index("draft") < states.index("verify")
    assert states.index("triage") < states.index("look")


def test_no_page_text_and_no_image_bytes_travel_in_the_answer(asking: Any):
    """P2 at the answer surface: a trace is a record of moves, not a copy of the corpus."""
    body = asking.ask(ASK_ANSWER_QUESTION).text

    assert "bytes_b64" not in body
    assert "Category 3 PL=D Reached" not in body, (
        "that line is page 19's own text; the answer carries the model's extract and the codes "
        "the gate cleared, never the page")


# ── the gate, on both routes (§8.1a, §8.4) ──────────────────────────────────────────────────────

def submitted(asking: Any, question: str, *, code: str, page_id: str,
              text: str = "") -> Any:
    """A draft the *calling agent* wrote — §8.1a's `fetch` route, submitted to be gated."""
    return asking.gate(question, draft={
        "text": text or f"The sheet names {code}.",
        "claims": [{"code": code, "page_ids": [page_id]}],
        "pages": [page_id],
    })


def test_a_code_nobody_could_check_renders_carrying_the_read_from_image_badge(asking: Any):
    """§8.4: *"`unverifiable` → render with the badge"*. Page 1 of this corpus is a scan.

    The honest outcome on a page with no text layer, and the reason the vocabulary has three
    states: telling a reader *"that code is not on the page"* about a page nobody could read
    converts our blind spot into their confident denial (R2, §5.7).
    """
    page_id = asking.page_id(1)
    payload = submitted(asking, "what does the cover sheet name",
                        code="C24", page_id=page_id).json()

    assert payload["status"] == "answered"
    assert payload["route"] == "fetch"
    assert payload["reads"] == 0, "the agent looked; nothing was delegated and nothing was billed"
    claim = payload["answer"]["claims"][0]
    assert (claim["status"], claim["badge"]) == ("unverifiable", BADGE_READ_FROM_IMAGE)
    assert payload["answer"]["warnings"], "the amber warning of §13 M7 rides with it"
    assert payload["checks"] == [{"claim": "C24", "page_id": page_id, "status": "unverifiable"}]


def test_a_draft_carrying_an_unverified_code_is_rejected_and_not_rendered(asking: Any):
    """I8's whole point (§13 M6): *"a draft containing an unverified code is rejected, not rendered"*.

    `K152` is printed on no page of this document. The draft that cites it renders **not at all**
    — not the code, not the sentence around it — and what comes back instead is an abstention
    carrying `present_instead`: what page 19 really prints.
    """
    page_id = asking.page_id(19)
    response = submitted(asking, ASK_REJECTED_QUESTION, code="K152", page_id=page_id)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "abstained" and payload["answer"] is None
    assert "K152" not in response.text and "k152" not in response.text, (
        "the misread code appears nowhere in what the caller receives (§8.4)")
    assert payload["abstention"]["reason"] == "rejected"
    assert payload["abstention"]["rejected_claims"] == 1
    assert payload["checks"] == [{"claim": "", "page_id": page_id, "status": "absent"}], (
        "the check is still auditable with its claim redacted")


def test_a_submitted_draft_is_gated_on_the_codes_in_its_prose_not_on_the_ones_it_declared(
        asking: Any):
    """The claim set is **re-derived** from the draft, never taken from the caller (§8.4).

    A caller that listed two of the three codes its own sentence contains would otherwise have the
    third rendered with nothing having checked it — on precisely the route where §8.1a says nothing
    else checked anything. So the draft below declares **no** claims at all, and the gate still
    finds `K152` in the prose, checks it against the page it is cited on, and refuses the whole
    thing. Found by the M6 gate review, which is why it is a row of its own.
    """
    page_id = asking.page_id(19)
    response = asking.client.post("/ask", headers=asking.header, json={
        "question": ASK_REJECTED_QUESTION,
        "draft": {"text": "The interlock relay K152 switches contactor Q69 on this sheet.",
                  "claims": [], "pages": [page_id]},
    })

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["checks"], "an undeclared code reached the gate unchecked"
    assert payload["status"] == "abstained" and payload["answer"] is None
    assert "K152" not in response.text and "k152" not in response.text
    assert {row["page_id"] for row in payload["checks"]} == {page_id}
    assert [row["status"] for row in payload["checks"] if row["claim"] == "q69"] == ["present"], (
        "the other code the prose carried **is** printed on page 19, so it was checked and came "
        "back present — the union is checked, not filtered. It renders nowhere all the same: one "
        "rejection discards the whole draft (§8.4)")


def test_the_gate_runs_on_the_fetch_route_exactly_as_it_does_on_the_read_route(asking: Any):
    """The same claim, both routes, the same verdict — §8.4 is *unconditional*.

    On the `read` route the loop obtained `K152` from a frozen response and Loop 1 stamped it
    `absent` inside the tool; on the `fetch` route nothing stamped anything, because the agent
    looked at the picture itself. Both drafts die at the same gate, which is the property that
    makes a `fetch`-first runner safe (§8.1a).
    """
    page_id = asking.page_id(20)
    through_loop = asking.ask(ASK_REJECTED_QUESTION).json()
    through_gate = submitted(asking, ASK_REJECTED_QUESTION,
                             code="K152", page_id=page_id).json()

    assert through_loop["route"] == "read" and through_gate["route"] == "fetch"
    assert through_loop["status"] == through_gate["status"] == "abstained"
    assert through_loop["abstention"]["rejected_claims"] >= 1
    assert through_gate["abstention"]["rejected_claims"] == 1
    for payload in (through_loop, through_gate):
        assert "K152" not in json.dumps(payload)
        assert "loop2_verify" in payload["loops"], "the gate ran on both routes"


# ── the abstention (§8.5) ───────────────────────────────────────────────────────────────────────

def test_the_abstention_names_the_coverage_numbers(asking: Any):
    """§13 M6: *"the failure branch abstains **with coverage numbers**"*.

    And it earns the right to sound complete: the draft was rejected, the scope was widened, and
    Loop 5 then **looked at both image-only pages** before anything was concluded — so
    `pages_no_text_read` equals `scope_stats.pages_no_text` and §8.5's sentence is available. The
    numbers are in the body as fields, not only in the prose, because a console renders them.
    """
    payload = asking.ask(ASK_REJECTED_QUESTION).json()
    abstention = payload["abstention"]

    assert abstention["reason"] == "rejected"
    assert abstention["pages_searched"] == 42
    assert abstention["searched"] == ["vsir-raster"]
    assert abstention["pages_no_text"] == 2 and abstention["pages_no_text_read"] == 2, (
        "the escalation of Loop 5 read them: that is what makes the corpus *searched*")
    assert abstention["image_only_unexamined"] == 0
    assert "42 page(s) searched across 1 document(s)" in abstention["text"]
    assert "All 2 image-only page(s) in scope were examined" in abstention["text"]


def test_the_abstention_cannot_claim_the_corpus_is_exhausted_while_a_page_is_unexamined(
        asking: Any):
    """§8.5's one prohibition, end to end — the same question with the blind spot out of reach.

    `exclude` is the caller saying *"I have already rejected those pages"*, so Loop 5 has nothing
    left to escalate to and two image-only pages stay unexamined. The corpus has therefore **not**
    been searched, and the sentence *"not in these documents"* is unavailable: an abstention that
    sounds complete is a fabricated absence in the one direction nobody audits.
    """
    payload = asking.ask(ASK_REJECTED_QUESTION,
                         exclude=asking.page_ids(1, 2)).json()
    abstention = payload["abstention"]

    assert FORBIDDEN_WORDING not in abstention["text"].lower(), abstention["text"]
    assert abstention["pages_no_text"] == 2 and abstention["pages_no_text_read"] == 0
    assert abstention["image_only_unexamined"] == 2
    assert "2 image-only page(s) in vsir-raster were not examined" in abstention["text"]
    assert "loop5_vision_escalation" in payload["loops"], (
        "the escalation still fired — it found nothing to look at, which is a different fact "
        "from not having tried")


# ── the budget (§8.4, §7.3) ─────────────────────────────────────────────────────────────────────

def test_reads_remaining_is_on_the_answer_the_abstention_and_the_refusal(asking: Any,
                                                                         qdrant: Any):
    """§7.1 puts it on every envelope; §8.4 says the caller gets that integer and not a cost."""
    answered = asking.ask(ASK_ANSWER_QUESTION).json()
    abstained = asking.ask(ASK_REJECTED_QUESTION).json()

    assert answered["reads_remaining"] > 0 and abstained["reads_remaining"] > 0
    assert "usd" not in json.dumps(answered), "cost goes to the audit log, never the body (§7.4)"

    with variant(asking, qdrant, VSIR_READS_PER_QUESTION="1") as client:
        refused = ask(client, ASK_LADDER_QUESTION)
        assert refused.status_code == 429
        assert "reads_remaining" in refused.json()


def test_the_per_question_ceiling_refuses_rather_than_answering_from_pages_that_did_not_answer(
        asking: Any, qdrant: Any):
    """§8.4: *"never a silent extra call and never an answer composed from a page the model said
    did not answer"*.

    `SI4` is printed on ten pages; the first three do not answer, so the loop needs a second look
    — which is legitimate, and which `VSIR_READS_PER_QUESTION=1` makes unaffordable. The honest
    outcome is `429 budget_exhausted` and no prose at all.
    """
    with variant(asking, qdrant, VSIR_READS_PER_QUESTION="1") as client:
        response = ask(client, ASK_LADDER_QUESTION)

        assert response.status_code == 429, response.text
        payload = response.json()
        assert payload["error"] == "budget_exhausted"
        assert "answer" not in payload and "abstention" not in payload, (
            "a spent budget is a refusal: nothing about the corpus was concluded")


def test_the_same_question_answers_when_the_second_look_is_affordable(asking: Any):
    """The control for the row above: the ceiling refused a call the default budget affords.

    Without it, `429` could be coming from anywhere — this is the same question, two reads, and
    an answer, which is Loop 3 spending its legitimate second read (§8.4).
    """
    payload = asking.ask(ASK_LADDER_QUESTION).json()

    assert payload["status"] == "answered"
    assert payload["reads"] == 2
    assert payload["answer"]["citations"] == asking.page_ids(*case("ask_pool")["pages"])


# ── an outage is an error, never an abstention (§7.1, §11.3) ────────────────────────────────────

def test_a_store_outage_mid_loop_is_an_error_and_never_an_abstention(asking: Any, qdrant: Any):
    """The risk this unit's plan names first: our outage delivered as the agent's fabricated absence.

    The loop's very first move is a tool call, so a store that does not answer refuses the whole
    question with the tool's own `503` — and the body contains no abstention, no coverage numbers
    and nothing that could be read as *"we looked and it is not there"*.
    """
    with variant(asking, qdrant, VSIR_QDRANT_URL=UNREACHABLE_URL) as client:
        response = ask(client, ASK_ANSWER_QUESTION)

        assert response.status_code == 503, response.text
        payload = response.json()
        assert payload["error"] == "qdrant_unavailable"
        assert payload.get("retryable") is True
        assert "abstention" not in payload and "not found" not in response.text.lower()
        assert "6399" not in response.text, "a refusal names no URL (§15.1)"


# ── the surface itself (§7.4) ───────────────────────────────────────────────────────────────────

def test_ask_requires_a_bearer_token(asking: Any):
    """§7.4: every path but the three probes and the description needs a credential."""
    response = asking.client.post("/ask", json={"question": ASK_ANSWER_QUESTION})

    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


def test_a_question_with_no_words_is_refused_before_any_call(asking: Any):
    """A `400` from the loop rather than three round trips ending in the same refusal."""
    response = asking.ask("   ")

    assert response.status_code == 400
    assert response.json()["error"] == "question_required"


def test_an_unknown_parameter_is_a_typed_400_and_never_a_quietly_different_question(asking: Any):
    """``extra="forbid"``: a misspelt parameter silently ignored is how a caller is told, with a
    straight face, that the corpus does not contain what they asked about."""
    response = asking.client.post(
        "/ask", headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        json={"question": ASK_ANSWER_QUESTION, "scpoe": {"doc_id": "vsir-raster"}})

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"
    assert response.json()["problems"][0]["field"] == "scpoe"


def test_ask_is_the_only_route_that_may_return_prose(asking: Any):
    """§7.4, asserted by scanning **every** route's published response schema.

    An answer is a composed statement about the corpus, and §7.6 refuses to let any tool make
    one: only the runner composes, and only behind the gate. So exactly one operation in the whole
    document may publish an :class:`~vsir.runner.answer.Answer`, and this finds out which by
    resolving each operation's 200 schema rather than by trusting a list.
    """
    document = asking.client.app.openapi()
    schemas = document["components"]["schemas"]

    def references(schema: Any, seen: set[str]) -> set[str]:
        """Every schema name reachable from here, following `$ref`s."""
        if isinstance(schema, dict):
            found: set[str] = set()
            ref = schema.get("$ref")
            if isinstance(ref, str):
                name = ref.rsplit("/", 1)[-1]
                if name not in seen:
                    seen.add(name)
                    found |= {name} | references(schemas.get(name, {}), seen)
                return found
            for value in schema.values():
                found |= references(value, seen)
            return found
        if isinstance(schema, list):
            return set().union(*(references(item, seen) for item in schema)) if schema else set()
        return set()

    prose_surfaces = set()
    for path, operations in document["paths"].items():
        for method, operation in operations.items():
            content = ((operation.get("responses") or {}).get("200") or {}).get("content") or {}
            for media in content.values():
                if "Answer" in references(media.get("schema") or {}, set()):
                    prose_surfaces.add(f"{method.upper()} {path}")

    assert prose_surfaces == {"POST /ask"}, prose_surfaces


def test_the_whole_loop_reaches_nothing_but_the_store(asking: Any, monkeypatch: Any):
    """The plan's own criterion: *"a network spy records zero outbound calls"* (§12.2, D10).

    Zero outbound calls **to a model**: the loop reads Qdrant, which is a socket, so the spy
    records every address this process connects to and the assertion is that the only port
    reached is the configured store's. `VSIR_VLM=stub` selects the replay backend and no
    credential is ever set, so a `read` that tried to reach Gemini would have nothing to try
    with — this is the row that proves it did not try.
    """
    seen: list[tuple[str, int]] = []
    real_connect = socket.socket.connect

    def spy(self: Any, address: Any, *rest: Any) -> Any:
        if isinstance(address, tuple) and len(address) >= 2:
            seen.append((str(address[0]), int(address[1])))
        return real_connect(self, address, *rest)

    monkeypatch.setattr(socket.socket, "connect", spy)

    payload = asking.ask(ASK_ANSWER_QUESTION).json()

    assert payload["status"] == "answered" and payload["reads"] == 1, (
        "the spy has to be watching a run that really did make the paid move")
    assert seen, "the spy recorded nothing at all, so it is not watching the right call"
    store = int(asking.config.qdrant_url.rsplit(":", 1)[-1])
    assert {port for _host, port in seen} == {store}, seen
    assert not [host for host, _port in seen if "google" in host or "gemini" in host]


def test_the_effective_scope_is_echoed_back_because_the_service_holds_no_session(asking: Any):
    """C11, F8: the scope the loop finished on travels with the answer, and nothing is remembered."""
    payload = asking.ask(ASK_ANSWER_QUESTION,
                  scope={"doc_id": "vsir-raster"}).json()

    assert payload["effective_scope"]["doc_id"] == "vsir-raster"
    assert payload["status"] == "answered"


@pytest.mark.parametrize("question, expected_state", [
    (ASK_ANSWER_QUESTION, "answered"),
    (ASK_REJECTED_QUESTION, "abstained"),
])
def test_two_questions_asked_twice_answer_the_same_way(asking: Any, question: str,
                                                       expected_state: str):
    """Determinism (§16): the same question and the same corpus make the same moves.

    A second `read` of the same pages and question is served from the control plane's own cache
    (§6.3, F19), so this row also asserts that a repeat costs nothing new — the answer is
    identical, including its citations.
    """
    first, second = asking.ask(question).json(), asking.ask(question).json()

    assert first["status"] == second["status"] == expected_state
    assert [move["state"] for move in first["trace"]] == [move["state"] for move in second["trace"]]
    assert first["answer"] == second["answer"]
    assert first["checks"] == second["checks"]
