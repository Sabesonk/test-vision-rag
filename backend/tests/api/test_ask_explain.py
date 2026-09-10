"""L2 — `vsir ask --explain`: the descent, the tri-state marks and the route, over a real index.

`test_triage.py`, `test_safeguards.py` and `test_route.py` assert the runner's decisions as
library behaviour on rows built in memory. This suite asserts the two things only a real store
can show:

* **the marks are made on rows a real fused search actually returns** — a triage that only ever
  saw hand-made `PageHit`s would be a triage of a shape, not of a corpus, and `why`,
  `grounded_rate` and `text_trust` are exactly the fields a fixture is tempted to make tidy;
* **`exclude` works as an argument, not as an intention** — the rejected pages go back into
  `skim_pages` and do not come out again.

And one property that is the whole reason U021 sits in a paid milestone and spends nothing: a
full `--explain` run bills nothing. That is asserted three ways here — the command's own spy, an
independent counter on the VLM backend factory, and the absence of an audit line, since §7.4
audits precisely the two tools that could have cost anything.

The command runs **in this process** through :func:`vsir.cli.main`, against the L2 Qdrant and the
multi-document U019 corpus. In-process because the exit code, the printed plan and the JSON event
lines are all part of the contract and all three are observable here.
"""
from __future__ import annotations

import json
from typing import Any, Iterator

import pytest
from qdrant_client import QdrantClient

from vsir import cli
from vsir import vlm as vlm_module
from vsir.runner import route as route_module
from vsir.runner.triage import MARKS, SAFEGUARDS, triage
from vsir.serve.envelope import PageHit

from conftest import AGGREGATE_COLLECTION, AGGREGATE_RUNS, QDRANT_URL, serve_env

#: The question the §0 M6 demo asks, and the one the U021 plan prints in its demo command.
QUESTION = "the carton discharge won't restart after an E-stop reset"

#: A question this corpus cannot answer. Every summary in it is about the carton discharge and the
#: emergency stop reset, so nothing here overlaps — which is what produces `irrelevant` rows to
#: exclude, and it produces them from the corpus rather than from a hand-made row.
OFF_TOPIC = "lubrication schedule for the gearbox bearings"

PAGES = "/tools/skim_pages"


@pytest.fixture
def ask_env(monkeypatch: pytest.MonkeyPatch, aggregate_collection: str,
            qdrant: QdrantClient) -> Iterator[dict[str, str]]:
    """The environment `vsir ask` reads, pointed at the U019 corpus. Nothing leaks out of a test.

    `VSIR_LOG_LEVEL=DEBUG` because the triage marks of §11.4 are debug events — free tools log at
    debug on purpose — and a suite that asserts they were written has to be able to see them.
    """
    env = serve_env(VSIR_COLLECTION=AGGREGATE_COLLECTION, VSIR_RUNS_COLLECTION=AGGREGATE_RUNS,
                    VSIR_QDRANT_URL=QDRANT_URL, VSIR_LOG_LEVEL="DEBUG")
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    try:
        yield env
    finally:
        if qdrant.collection_exists(AGGREGATE_RUNS):
            qdrant.delete_collection(AGGREGATE_RUNS)


@pytest.fixture
def no_paid_backend(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """An independent spy on the seam a paid call must come through (`vlm.backend`).

    The command carries its own spy and prints what it saw; this one is outside the command, so a
    run that reported *"zero paid calls"* while building a live client would still fail here.
    """
    reached: list[str] = []

    def refuse(cfg: Any) -> Any:
        reached.append(cfg.vlm_model)
        raise AssertionError("a VLM backend was built during a free command")

    monkeypatch.setattr(vlm_module, "backend", refuse)
    yield reached
    assert reached == []


def run(*argv: str) -> int:
    return cli.main(list(argv))


def events(output: str) -> list[dict[str, Any]]:
    """The JSON event lines out of the command's stdout — the human rendering shares the stream."""
    return [json.loads(line) for line in output.splitlines() if line.startswith("{")]


def rows_of(client: Any, headers: dict[str, str], **body: Any) -> list[PageHit]:
    """One real `skim_pages`, as the runner receives it: validated `PageHit`s, nothing else."""
    response = client.post(PAGES, json=body, headers=headers)
    assert response.status_code == 200, response.text
    return [PageHit.model_validate(hit) for hit in response.json()["hits"]]


# ── the command ─────────────────────────────────────────────────────────────────────────────────

def test_the_explain_run_descends_the_ladder_and_ends_green(ask_env, no_paid_backend, capsys):
    """§8.1's descent, §8.2's marks, §8.1a's route — one command, exit 0, nothing spent."""
    assert run("ask", "--explain", QUESTION) == 0
    out = capsys.readouterr().out
    for expected in ("01 DESCEND — skim_documents", "02 DESCEND — skim_sections",
                     "03 DESCEND — skim_pages", "04 TRIAGE", "05 EXCLUDE", "06 ROUTE",
                     "07 MACHINE", "08 SPEND", "ALL ASSERTIONS PASSED"):
        assert expected in out, f"the plan does not show {expected!r}\n{out}"


def test_the_run_reaches_no_paid_tool_and_leaves_the_budget_where_it_found_it(
        ask_env, no_paid_backend, capsys):
    """Three independent statements of *"triage and routing are decided before money moves"*."""
    assert run("ask", "--explain", QUESTION) == 0
    out = capsys.readouterr().out
    assert "paid [] · VLM backend reached 0 time(s)" in out
    dispatched = [event.get("tool") for event in events(out) if event.get("tool")]
    assert "read" not in dispatched and "fetch" not in dispatched
    # §7.4 audits the two tools that spend and nothing else, so an audit line is the record a
    # free command must not produce.
    assert not [event for event in events(out) if event.get("event") == "audit"]


def test_the_marks_reach_telemetry_and_the_run_does_not_depend_on_them(ask_env, no_paid_backend,
                                                                      capsys):
    """§8.2, §11.4 — `query → page → relevant?` as free evaluation data, never a tool call."""
    assert run("ask", "--explain", QUESTION) == 0
    out = capsys.readouterr().out
    marks = [event for event in events(out) if event.get("event") == "triage_mark"]
    assert marks, "no triage mark reached the event stream"
    assert {event["query"] for event in marks} == {QUESTION}
    assert all(event["mark"] in MARKS for event in marks)
    assert all(event["page_id"] and event["reason"] for event in marks)
    assert f"telemetry {len(marks)} mark(s)" in out


def test_the_default_route_is_fetch_and_a_text_only_caller_is_delegated_to_read(
        ask_env, no_paid_backend, capsys):
    """§8.1a, both input shapes, through the shipped command (SA-4)."""
    assert run("ask", "--explain", QUESTION) == 0
    seeing = capsys.readouterr().out
    assert "fetch   default_fetch" in seeing
    assert "vision-capable" in seeing

    assert run("ask", "--explain", "--no-vision", QUESTION) == 0
    blind = capsys.readouterr().out
    assert "read    caller_not_vision_capable" in blind
    assert "spends true" in blind


def test_the_prompt_is_identified_and_can_be_printed(ask_env, no_paid_backend, capsys):
    assert run("ask", "--explain", "--prompt", QUESTION) == 0
    out = capsys.readouterr().out
    assert "runner-v1 · sha256" in out and f"{len(SAFEGUARDS)} safeguard(s) bound" in out
    assert "Mark each row `relevant`, `uncertain` or `irrelevant`" in out
    for name, rule in SAFEGUARDS:
        assert name in out and rule in out


def test_an_empty_triage_branches_on_coverage_and_still_proves_it_spent_nothing(
        ask_env, no_paid_backend, capsys):
    """§8.1's second empty row: pages have no text, so vision goes first and §8.5 binds the words.

    `K999` is the hallucinated code of I2 — it is printed nowhere — so the phrase filter empties
    every rung and there is nothing to mark. The run is still a success: an absence the corpus
    genuinely has is a correct answer (§7.1), and the branch it takes is decided by coverage.
    """
    assert run("ask", "--explain", "where is K999 wired") == 0
    out = capsys.readouterr().out
    assert "no candidates to mark" in out
    assert "§8.1 branch: empty_no_text → vision_first" in out
    assert "image-only page(s) in scope are unexamined" in out
    assert '"Not in these documents" is forbidden until they are (§8.5)' in out
    assert "next.suggest ['lookup']" in out
    assert "08 SPEND" in out and "ALL ASSERTIONS PASSED" in out


def test_without_explain_the_command_refuses_and_names_what_owns_the_answer(capsys):
    """Composing prose is the gate's (§8.4, I8) and is U022's. Not a stub, a named refusal."""
    assert run("ask", QUESTION) != 0
    out = capsys.readouterr().out
    assert "answer_not_built" in out and "U022" in out


# ── the marks, on rows a real search returned ───────────────────────────────────────────────────

def test_every_candidate_of_a_real_fused_search_is_marked(aggregating, token_header):
    """The rows carry a real `why`, a real `grounded_rate` and a real `text_trust` (§7.1)."""
    hits = rows_of(aggregating, token_header, query=QUESTION, limit=10)
    assert hits, "the corpus returned no candidate to triage"
    result = triage(hits, query=QUESTION)
    assert len(result.marks) == len(hits)
    assert {one.page_id for one in result.marks} == {hit.page_id for hit in hits}
    assert all(one.mark in MARKS for one in result.marks)
    assert len(result.relevant) + len(result.uncertain) + len(result.irrelevant) == len(hits)


def test_a_page_with_no_text_layer_is_never_marked_irrelevant(aggregating, token_header):
    """R1, on the pages vision exists for: a scanned page's silence is not evidence (§5.7, F4)."""
    hits = rows_of(aggregating, token_header, query=OFF_TOPIC, limit=10)
    result = triage(hits, query=OFF_TOPIC)
    scanned = {hit.page_id for hit in hits if hit.text_trust in ("no_text", "untrusted")}
    excluded = set(result.exclude)
    assert not scanned & excluded, f"a scanned page was excluded: {sorted(scanned & excluded)}"


def test_an_irrelevant_candidate_goes_into_exclude_and_never_comes_back(aggregating,
                                                                       token_header):
    """The AC, proved by using the argument: re-skim with `exclude` and check the rows are gone."""
    hits = rows_of(aggregating, token_header, query=OFF_TOPIC, limit=10)
    result = triage(hits, query=OFF_TOPIC)
    assert result.irrelevant, (
        f"{len(hits)} candidate(s) and none irrelevant — the off-topic query no longer produces "
        f"an exclusion to prove")
    again = rows_of(aggregating, token_header, query=OFF_TOPIC, limit=10,
                    exclude=list(result.exclude))
    returned = {hit.page_id for hit in again}
    assert not returned & set(result.exclude)


def test_the_look_set_routes_within_the_caps_the_server_enforces(aggregating, token_header):
    """A route is only useful if it plans a call `fetch` or `read` would accept (§7.3)."""
    hits = rows_of(aggregating, token_header, query=QUESTION, limit=10)
    result = triage(hits, query=QUESTION)
    seeing = route_module.plan(result.look_set, route_module.Caller(reads_remaining=3))
    blind = route_module.plan(result.look_set,
                              route_module.Caller(reads_remaining=3, vision_capable=False))
    assert len(seeing.pages) <= seeing.decision.cap
    assert len(blind.pages) <= blind.decision.cap
    assert set(seeing.pages) | set(seeing.deferred) == set(result.look_set)
