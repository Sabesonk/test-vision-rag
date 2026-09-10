"""L2 — `GET /runs/{run_id}`, the two exports and the §11.4 gauges, over real HTTP (§6.8, §6.9).

The suite drives the **container**, not an in-process app. That is the whole point of it: the run
was written by a process on this machine and is being read by a replica that never executed it, out
of `vsir_runs` (D9). `impl` could not do that at all — its run state was a dict on a daemon thread
(register **E2**), and its exports were files one instance had written to its own disk and the HTTP
path never wrote at all (register **E1**).

So three claims are checked here and each is a different failure:

* the run record survives the process that made it, and an unknown run is a **typed 404** rather
  than an empty record — a caller cannot tell an empty record from a run that found nothing;
* the exports stream **from the index**, with the §6.8 field set, and writing **no file** — checked
  by a spy over `open` while the same export runs in this process;
* the gauges are computed per scrape from the control plane, so any replica answers the same.
"""
from __future__ import annotations

import builtins
import json
import urllib.error
import urllib.request
from typing import Any, Sequence

import pytest
from qdrant_client.http import models as qm

from vsir.ingest import export as export_module
from vsir.ingest import gates, index as index_module
from vsir.ingest import run as run_module
from vsir.ingest.fingerprint import Fingerprint

from test_publish_and_retire import build_records

#: The **container's** collections, because this suite reads over HTTP: the server was configured
#: with `VSIR_COLLECTION=vsir_pages` and the default runs collection (docker-compose.test.yml).
EMBED_DIM = 1536
COLLECTION = f"vsir_pages_{EMBED_DIM}"
RUNS = "vsir_runs"
DOC = "RUNREC"
RUN_ID = "01J0RUNRECORD0000000000000"
PAGES = 6

FINGERPRINT = Fingerprint(embed_model="gemini-embedding-2", dim=EMBED_DIM)


def get(url: str) -> tuple[int, Any, dict[str, str]]:
    """One GET. A 4xx/5xx is a response to read, not an exception to raise (§7.1)."""
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            body = response.read().decode("utf-8")
            return response.status, body, dict(response.headers)
    except urllib.error.HTTPError as failure:
        return failure.code, failure.read().decode("utf-8"), dict(failure.headers)


@pytest.fixture(scope="module")
def published(qdrant, pages_collection) -> Any:
    """One published run in the collections the container serves from, dropped at teardown.

    `pages_collection` is the session fixture that creates `vsir_pages_1536` from `INDEXED` — the
    same collection `/ready` asserts against, so this suite adds to it rather than making its own,
    and removes exactly what it added.
    """
    records = build_records(DOC, "1.0", RUN_ID, pages=PAGES, doc_type="safety_function_list")
    vectors = {record.page_id: [0.01 * ((record.page_no + index) % 7)
                                for index in range(EMBED_DIM)] for record in records}
    index_module.upsert(qdrant, COLLECTION, list(records), vectors, fingerprint=FINGERPRINT,
                        runs_collection=RUNS)
    record = run_module.start(qdrant, RUNS, run_id=RUN_ID, doc_id=DOC, revision="1.0",
                              release_id="test-0", collection=COLLECTION, page_count=PAGES,
                              windows_total=1, owner="suite")
    run_module.note_window(qdrant, RUNS, run_module.WindowState(
        run_id=RUN_ID, doc_id=DOC, start=1, end=PAGES, state=run_module.DONE, attempts=1,
        checkpoint="derive", extract_key="deadbeef", pages_returned=PAGES))
    report = gates.evaluate(records=list(records), page_count=PAGES,
                            windows=[state.outcome() for state in
                                     run_module.windows(qdrant, RUNS, RUN_ID)])
    record = run_module.save(qdrant, RUNS, record.model_copy(update={"windows_done": 1}))
    try:
        yield run_module.publish(qdrant, runs_collection=RUNS, collection=COLLECTION,
                                 record=record, report=report, records=list(records), by="suite")
    finally:
        # Exactly what this suite added, and nothing else: `vsir_pages_1536` is the session's
        # collection and another L2 suite is entitled to find it as it left it.
        qdrant.delete(COLLECTION, points_selector=qm.Filter(must=[
            qm.FieldCondition(key="doc_id", match=qm.MatchValue(value=DOC))]), wait=True)
        qdrant.delete(RUNS, points_selector=[
            run_module.run_point_id(RUN_ID), run_module.inventory_point_id(DOC),
            run_module.window_point_id(RUN_ID, 1, PAGES)], wait=True)


# ── GET /runs/{run_id} — §6.9, every field ───────────────────────────────────────────────────────

def test_the_run_record_carries_every_field_of_6_9(base_url, published):
    """AC: `gate_results`, `overrides`, `lease` and `cost` among them — and the replica answering
    is not the process that wrote them."""
    status, body, _ = get(f"{base_url}/runs/{RUN_ID}")
    record = json.loads(body)

    assert status == 200
    for field in ("run_id", "doc_id", "revision", "release_id", "state", "step", "windows_done",
                  "windows_total", "pages_indexed", "gate_results", "overrides", "published_at",
                  "lease", "failed", "cost"):
        assert field in record, f"§6.9 names {field} and the response does not carry it"
    assert record["state"] == "published" and record["published_at"]
    assert record["doc_id"] == DOC and record["pages_indexed"] == PAGES
    assert sorted(record["gate_results"]) == sorted(gates.GATES)
    assert {"input_tokens", "output_tokens", "cache_hits"} <= set(record["cost"])


def test_the_state_is_one_of_the_six_of_6_9(base_url, published):
    status, body, _ = get(f"{base_url}/runs/{RUN_ID}")

    assert status == 200
    assert json.loads(body)["state"] in run_module.RUN_STATES


def test_an_unknown_run_is_a_typed_404_and_not_an_empty_record(base_url, published):
    """§11.3, §7.1 — distinct failures stay distinct. An empty record is indistinguishable from a
    run that produced nothing, which is exactly the empty-`200` abstention §2.5 A deletes."""
    status, body, _ = get(f"{base_url}/runs/01J0NOSUCHRUN000000000000")
    payload = json.loads(body)

    assert status == 404
    assert payload["error"] == "run_not_found"
    assert payload["run_id"] == "01J0NOSUCHRUN000000000000"


def test_the_window_points_are_readable_beside_the_run(qdrant, published):
    """§6.7 — one point per window: `{state, attempts, checkpoint, extract_key}`. It is what
    `offset_check` reads at step 11 and what `--resume` will read at U025."""
    windows = run_module.windows(qdrant, RUNS, RUN_ID)

    assert len(windows) == 1
    assert windows[0].state == run_module.DONE and windows[0].checkpoint == "derive"
    assert windows[0].extract_key == "deadbeef" and windows[0].window == [1, PAGES]
    assert windows[0].outcome().offset_ok


# ── the two exports of §6.8, streamed over HTTP ──────────────────────────────────────────────────

def test_labels_jsonl_streams_one_line_per_page_with_the_6_8_field_set(base_url, published):
    """AC: `page_id`, `doc_id`, `revision`, `page_no`, `printed_page_no`, `label_verified`,
    `sections[]` (with `section_id`, `title`, `page_range`, `series_id`), `summaries[]`,
    `codes_in_text[]`, `grounded_rate`, `safety_flag`, `vlm_model`, `prompt_version`, `dpi`."""
    status, body, headers = get(f"{base_url}/runs/{RUN_ID}/export/labels.jsonl")
    rows = [json.loads(line) for line in body.splitlines() if line]

    assert status == 200
    assert headers.get("content-type", "").startswith("application/x-ndjson")
    assert len(rows) == PAGES
    assert [row["page_no"] for row in rows] == list(range(1, PAGES + 1))
    for row in rows:
        assert sorted(row) == sorted(export_module.LABEL_FIELDS)
        assert sorted(row["sections"][0]) == sorted(export_module.SECTION_FIELDS)
        assert row["vlm_model"] and row["prompt_version"] and row["dpi"] == 220


def test_observed_tokens_jsonl_streams_one_line_per_document(base_url, published):
    """AC: one line per document — the inventory that backs `present_instead` (C7)."""
    status, body, _ = get(f"{base_url}/runs/{RUN_ID}/export/observed_tokens.jsonl")
    rows = [json.loads(line) for line in body.splitlines() if line]

    assert status == 200
    assert len(rows) == 1
    assert rows[0]["doc_id"] == DOC and rows[0]["token_count"] == len(rows[0]["tokens"])
    assert all(any(character.isdigit() for character in token) for token in rows[0]["tokens"])


def test_the_export_of_an_unknown_run_is_a_typed_404(base_url, published):
    status, body, _ = get(f"{base_url}/runs/01J0NOSUCHRUN000000000000/export/labels.jsonl")

    assert status == 404
    assert json.loads(body)["error"] == "run_not_found"


def test_the_dropped_third_file_is_a_typed_404_rather_than_an_empty_stream(base_url, published):
    """`withheld.jsonl` is gone with the allowlist gate that produced it (§2.4, §2.5 B). An empty
    `200` would let a consumer conclude the document withheld nothing."""
    status, body, _ = get(f"{base_url}/runs/{RUN_ID}/export/withheld.jsonl")

    assert status == 404
    assert json.loads(body)["error"] == "export_refused"


def test_no_export_file_is_written_to_the_instance_disk(qdrant, published, monkeypatch, tmp_path):
    """AC: a filesystem-write spy confirms **no** export file is written during either request.

    The spy runs in this process over the same generator the endpoint returns, because a spy
    cannot be installed inside the container — and the generator *is* the endpoint's body, so
    what is proved here is what the request does.
    """
    opened: list[str] = []
    real_open = builtins.open

    def spy(file, mode="r", *args, **kwargs):
        if any(flag in str(mode) for flag in ("w", "a", "x", "+")):
            opened.append(f"{file}:{mode}")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spy)
    monkeypatch.chdir(tmp_path)

    rows = list(export_module.stream(qdrant, artefact="labels", collection=COLLECTION,
                                     runs_collection=RUNS, record=published))
    rows += list(export_module.stream(qdrant, artefact="observed_tokens", collection=COLLECTION,
                                      runs_collection=RUNS, record=published))

    assert len(rows) == PAGES + 1
    assert opened == []
    assert list(tmp_path.iterdir()) == []


def test_the_safety_flag_is_configuration_and_the_container_sets_none(base_url, published):
    """§6.8 — `SAFETY_DOC_TYPES` is a manifest facet an operator declares, and the test stack
    declares none. So the same document that flags `True` in `test_publish_and_retire` (which
    passes the set explicitly) flags `False` here: no list is compiled into the image."""
    status, body, _ = get(f"{base_url}/runs/{RUN_ID}/export/labels.jsonl")
    rows = [json.loads(line) for line in body.splitlines() if line]

    assert status == 200
    assert all(row["safety_flag"] is False for row in rows)


# ── GET /metrics — §11.4 ─────────────────────────────────────────────────────────────────────────

def test_the_prometheus_endpoint_exposes_both_gauges(base_url, published):
    """AC: `ingest_grounded_rate_median{doc_id}` and `ingest_gate_failures_total{gate}`."""
    status, body, headers = get(f"{base_url}/metrics")

    assert status == 200
    assert headers.get("content-type", "").startswith("text/plain")
    assert f'ingest_grounded_rate_median{{doc_id="{DOC}"}}' in body
    for gate in gates.GATES:
        assert f'ingest_gate_failures_total{{gate="{gate}"}}' in body
    assert "# TYPE ingest_grounded_rate_median gauge" in body


def test_the_gauges_are_recomputed_from_the_control_plane_on_every_scrape(base_url, published):
    """§15 Factor VI — no counter in this process, so a scrape after a restart is not a hole in
    the series and two replicas do not disagree."""
    first = get(f"{base_url}/metrics")[1]
    second = get(f"{base_url}/metrics")[1]

    assert first == second


# ── the probes are unaffected by any of it (§15.1) ───────────────────────────────────────────────

def test_health_and_ready_still_answer_beside_the_new_surface(base_url, published):
    """The run surface shares the process with the probes and must not slow or break them: they
    use a different client with a two-second timeout for exactly that reason."""
    assert json.loads(get(f"{base_url}/health")[1])["status"] == "ok"
    assert get(f"{base_url}/ready")[0] == 200
